#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What separates the depthwise channels that came out right from the ones that
did not.

Round 55 settled the attribution and left a much better starting point:

    mn_dw1    3 of 32 correct on the round 53 baseline -> 9 of 32
    mn_dw25   188 of 1024                              -> 432 of 1024

and it settled that the RECORD COUNT is inert: 4, 8 and 16 records on mn_dw1
and 128 against 256 on mn_dw25 all give byte identical output, even though each
moves the fp16 table and the 0x5024 operand with it. So what is load bearing is
the 48 byte stride and the weight buffer's zero point lane, and what is left
wrong is per channel.

Both models are per-TENSOR quantised, so scale, zero point and C are the same
for every channel. The only things that differ channel to channel are the bias
and the weight sum, which meet in A:

    A[oc] = bias[oc] - (in_zp - 0x80) * sum(w_q - wt_zp)

mn_dw1's input zero point is 0, so that second term is +128 * sw, and sw runs
over nine taps of (w_q - 110). This computes A for every channel and asks
whether the channels the board got right sit anywhere in particular.

DECISION RULE, written before the run:
  correct channels separate cleanly on |A|, or on sw, or on the bias
      -> a range or a saturation, and the next round tests that directly
  8 constant channels line up with something specific
      -> that is the failure mode to chase
  nothing separates
      -> A is not the remaining bug and the next round has to move elsewhere,
         with no build wasted on it
"""
import struct
import sys

import numpy as np

# From the round 55 board log, mn_dw1 on the shipped configuration.
CORRECT = [0, 3, 8, 9, 14, 20, 22, 27, 30]
N_CONST = 8          # channels the board reported CONSTANT
N_PINNED = 5         # of those, pinned at the output zero point


class T:
    def __init__(self, buf, pos):
        self.b, self.pos = buf, pos
        self.vt = pos - struct.unpack_from("<i", buf, pos)[0]

    def off(self, field):
        if 4 + field * 2 >= struct.unpack_from("<H", self.b, self.vt)[0]:
            return 0
        return struct.unpack_from("<H", self.b, self.vt + 4 + field * 2)[0]

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

    def tables(self, field):
        o = self.off(field)
        if not o:
            return []
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return [T(self.b, q + struct.unpack_from("<I", self.b, q)[0])
                for q in (p + 4 + i * 4 for i in range(n))]

    def u32(self, field, default=0):
        o = self.off(field)
        return struct.unpack_from("<I", self.b, self.pos + o)[0] if o else default

    def raw(self, field):
        o = self.off(field)
        if not o:
            return b""
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return self.b[p + 4:p + 4 + n]


def model(path):
    b = open(path, "rb").read()
    root = T(b, struct.unpack_from("<I", b, 0)[0])
    sub = root.tables(2)[0]
    bufs = root.tables(4)
    out = []
    for t in sub.tables(0):
        q = t.sub(4)
        out.append({
            "shape": t.vec(0, "i", 4),
            "buf": bufs[t.u32(2)],
            "scale": np.array(q.vec(2, "f", 4)) if q else np.array([]),
            "zp": np.array(q.vec(3, "q", 8)) if q else np.array([]),
        })
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "../rootfs-overlay/opt/npu-test/mn_dw1.tflite"
    ts = model(path)
    inp, wt, bias, outp = ts[0], ts[1], ts[2], ts[3]
    oc = wt["shape"][3]
    k = wt["shape"][1] * wt["shape"][2]

    w = np.frombuffer(wt["buf"].raw(0), dtype=np.uint8).astype(np.int64)
    b = np.frombuffer(bias["buf"].raw(0), dtype="<i4").astype(np.int64)
    print(f"== {path} ==")
    print(f"  {oc} channels, {k} taps, in_zp {inp['zp'][0]}, "
          f"wt_zp {wt['zp'][0]}, out_zp {outp['zp'][0]}")
    print(f"  weight bytes {len(w)} (expect {k*oc}), bias entries {len(b)}")
    if len(w) != k * oc or len(b) != oc:
        print("  buffers are not the expected size, stopping")
        return

    wt_zp = int(wt["zp"][0])
    in_zp = int(inp["zp"][0])
    wq = w.reshape(k, oc)                       # tflite depthwise is [1,ky,kx,C]
    sw = (wq - wt_zp).sum(axis=0)
    A = b - (in_zp - 0x80) * sw

    ok = np.array([c in CORRECT for c in range(oc)])
    for name, v in (("sum(w_q - wt_zp)", sw), ("bias", b), ("A", A),
                    ("|A|", np.abs(A))):
        print(f"\n  {name}")
        print(f"    correct channels: min {v[ok].min():12d} "
              f"max {v[ok].max():12d} mean {v[ok].mean():14.1f}")
        print(f"    wrong channels:   min {v[~ok].min():12d} "
              f"max {v[~ok].max():12d} mean {v[~ok].mean():14.1f}")
        # A clean separation means one set's range does not overlap the other.
        sep = v[ok].max() < v[~ok].min() or v[~ok].max() < v[ok].min()
        print(f"    ranges disjoint: {sep}")

    print("\n  per channel, sorted by |A|:")
    order = np.argsort(np.abs(A))
    for c in order:
        print(f"    ch {int(c):3d}  sw {int(sw[c]):7d}  bias {int(b[c]):9d}  "
              f"A {int(A[c]):10d}  {'CORRECT' if ok[c] else 'wrong'}")

    rank = {int(c): r for r, c in enumerate(order)}
    print(f"\n  mean |A| rank of correct channels: "
          f"{np.mean([rank[c] for c in CORRECT]):.1f} of {oc-1}")
    print(f"  mean |A| rank of wrong channels:   "
          f"{np.mean([rank[c] for c in range(oc) if c not in CORRECT]):.1f}")
    print(f"\n  A values that do not fit in int16: "
          f"{int((np.abs(A) > 32767).sum())} of {oc}")
    print(f"  A values that do not fit in int24: "
          f"{int((np.abs(A) > (1 << 23) - 1).sum())} of {oc}")


if __name__ == "__main__":
    main()
