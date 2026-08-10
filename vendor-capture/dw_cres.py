#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Round 54's result, read offline before the next board round.

mn_dw1 went from 5 of 32 channels correct to 9, and from 23 constant channels
to 8, when the derived depthwise table replaced the regular one. It is the
model whose geometry is EXACTLY the captured pair's, ic = oc = 32 at 112x112,
k = 3, s = 1. So the table is doing something, and 23 channels are still wrong.

WHICH channels are wrong is the evidence. If the record count or the table
offset were wrong, whole groups of eight would fail together, because that is
the granularity of a record. They do not: the correct set is
0, 3, 8, 9, 14, 20, 22, 27, 30, scattered across every group. That points at a
per-channel VALUE, and the only per-channel value in the record whose format
this driver chose rather than derived is C.

C is written as round(16 * wt_sc[oc] / max wt_sc), Q4, because the regular path
is byte exact on hardware with Q4 and railed with the vendor's Q14. Every
regular model here is per-TENSOR quantised, so every channel's ratio is exactly
1 and Q4 versus Q14 is a choice between 16 and 16384 with nothing in between to
get wrong. A per-AXIS depthwise layer is the opposite case: the ratios spread
across the whole range and Q4 rounds them to sixteenths.

PREDICTION, tested here with no board: the channels mn_dw1 gets right are the
ones whose scale ratio lands on a sixteenth, and the ones it gets wrong are the
ones Q4 rounds hardest. If that holds, C's resolution is the remaining bug. If
it does not, C is not the story and the next round has to look elsewhere. That
is the point of running it before building anything.

⚠ parse_tflite.py reads the Quantization table with scale at field 1 and zero
point at 2. The schema has min 0, max 1, scale 2, zero_point 3, so it returns
garbage for any tensor that carries min/max, which is why its output for this
model shows a scale of 5.99 and a zero point of 1019264715. The reader below
uses the right indices; that bug is left alone here rather than fixed blind,
since other scripts may be leaning on its current behaviour.
"""
import struct
import sys

import numpy as np

# From the round 54 board log, mn_dw1 on the derived table.
CORRECT = [0, 3, 8, 9, 14, 20, 22, 27, 30]


class T:
    """The two flatbuffer moves this needs: follow a field, read a vector."""

    def __init__(self, buf, pos):
        self.b, self.pos = buf, pos
        self.vt = pos - struct.unpack_from("<i", buf, pos)[0]

    def off(self, field):
        vt_len = struct.unpack_from("<H", self.b, self.vt)[0]
        slot = 4 + field * 2
        if slot >= vt_len:
            return 0
        return struct.unpack_from("<H", self.b, self.vt + slot)[0]

    def sub(self, field):
        o = self.off(field)
        if not o:
            return None
        p = self.pos + o
        return T(self.b, p + struct.unpack_from("<I", self.b, p)[0])

    def vec(self, field, fmt, size):
        o = self.off(field)
        if not o:
            return []
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return list(struct.unpack_from(f"<{n}{fmt}", self.b, p + 4))

    def vec_of_tables(self, field):
        o = self.off(field)
        if not o:
            return []
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        out = []
        for i in range(n):
            q = p + 4 + i * 4
            out.append(T(self.b, q + struct.unpack_from("<I", self.b, q)[0]))
        return out


def weight_scales(path):
    b = open(path, "rb").read()
    root = T(b, struct.unpack_from("<I", b, 0)[0])
    sub = root.vec_of_tables(2)[0]                 # Model.subgraphs
    tens = sub.vec_of_tables(0)                    # SubGraph.tensors
    out = []
    for i, t in enumerate(tens):
        q = t.sub(4)                               # Tensor.quantization
        if q is None:
            continue
        sc = q.vec(2, "f", 4)                      # Quantization.scale
        zp = q.vec(3, "q", 8)                      # Quantization.zero_point
        shape = t.vec(0, "i", 4)
        out.append((i, shape, np.array(sc), np.array(zp)))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "../rootfs-overlay/opt/npu-test/mn_dw1.tflite"
    print(f"== {path} ==")
    for i, shape, sc, zp in weight_scales(path):
        print(f"  T{i} shape {shape}: {len(sc)} scales, {len(zp)} zero points"
              + (f", scale[0] {sc[0]:.8f} zp[0] {zp[0]}" if len(sc) else ""))

    per_axis = [(i, shape, sc, zp) for i, shape, sc, zp in weight_scales(path)
                if len(sc) == 32]
    if not per_axis:
        print("\n  no 32-entry per-axis tensor: this model is per-tensor, so "
              "Q4 costs it nothing and the prediction cannot be tested here")
        return

    for i, shape, sc, zp in per_axis:
        rel = sc / sc.max()
        q4 = np.rint(16.0 * rel)
        err = np.abs(q4 / 16.0 - rel) / rel
        print(f"\n=== T{i} shape {shape}, C resolution under Q4 ===")
        print("  ch   ratio    Q4    Q4 error   correct on board")
        for c in range(32):
            print(f"  {c:2d}  {rel[c]:.4f}  {int(q4[c]):3d}   "
                  f"{err[c]*100:6.2f}%      {'yes' if c in CORRECT else 'no'}")
        ok = np.array([c in CORRECT for c in range(32)])
        print(f"\n  mean Q4 error, channels CORRECT on board: "
              f"{err[ok].mean()*100:.2f}%")
        print(f"  mean Q4 error, channels WRONG on board:   "
              f"{err[~ok].mean()*100:.2f}%")
        zero = [int(c) for c in np.where(q4 == 0)[0]]
        print(f"  channels whose Q4 rounds to ZERO: {zero}")
        order = np.argsort(err)
        rank = {int(c): r for r, c in enumerate(order)}
        print(f"  mean rank of correct channels (0 = least Q4 error): "
              f"{np.mean([rank[c] for c in CORRECT]):.1f} of 31")
        print(f"  mean rank of wrong channels:                        "
              f"{np.mean([rank[c] for c in range(32) if c not in CORRECT]):.1f}")


if __name__ == "__main__":
    main()
