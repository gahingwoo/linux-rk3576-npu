#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Read the vendor's 1x1 weight layout at ic AND oc above 32, with two probes.

posprobe_pw.py gives every (oc, ic) pair a distinct byte, which caps it at 255
positions, so every layout it has ever confirmed came from a model with oc at
or below 32. That is exactly where the layouts under test agree, and round 132
showed on hardware that they stop agreeing above it: with 64 input channels the
output channels split in two halves of 32 that see different halves of the
weight buffer.

So drop the requirement that a byte names the pair. Compile TWO models of the
same shape:

    probe A   the weight depends only on the output channel
    probe B   the weight depends only on the input channel

Each needs at most 64 distinct levels rather than 4096. Position i of the blob
then reads its output channel out of A and its input channel out of B, and the
two together give the whole map at any shape.

Usage: posprobe_pw2.py [ic] [oc] [hw]
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")

IC = int(sys.argv[1]) if len(sys.argv) > 1 else 64
OC = int(sys.argv[2]) if len(sys.argv) > 2 else 64
HW = int(sys.argv[3]) if len(sys.argv) > 3 else 40
A = 32                                    # the weight atomic size for int8


def build(name, levels):
    """levels[oc][ic] in weight units; compile it and return the .rknn bytes."""
    w = (levels.astype(np.float32) / 128.0).reshape(OC, IC, 1, 1)
    m = nn.Conv2d(IC, OC, 1, bias=True)
    with torch.no_grad():
        m.weight.copy_(torch.from_numpy(w))
        m.bias.zero_()
    m.eval()
    onnx = f"{OUT}/{name}.onnx"
    torch.onnx.export(m, torch.randn(1, IC, HW, HW), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)
    calib = f"{OUT}/{name}_c.npy"
    np.save(calib, (np.arange(IC * HW * HW).reshape(1, IC, HW, HW)
                    % 251).astype(np.uint8))
    ds = f"{OUT}/{name}_d.txt"
    open(ds, "w").write(os.path.abspath(calib) + "\n")

    from rknn.api import RKNN
    r = RKNN(verbose=False)
    r.config(target_platform="rk3576", quantized_method="layer")
    assert r.load_onnx(model=onnx) == 0
    assert r.build(do_quantization=True, dataset=ds) == 0
    rk = f"{OUT}/{name}_rk3576.rknn"
    assert r.export_rknn(rk) == 0
    r.release()

    # one scale for the whole tensor, so the levels stay distinct and monotone
    scale = float(np.abs(w).max()) / 127.0
    q = np.clip(np.round(w.reshape(OC, IC) / scale), -128, 127).astype(np.int8)
    return open(rk, "rb").read(), q


def locate(data, q):
    """The blob is IC*OC bytes drawn from q's value set with q's multiplicities."""
    need = IC * OC
    vals, counts = np.unique(q.astype(np.uint8), return_counts=True)
    want = dict(zip(vals.tolist(), counts.tolist()))
    arr = np.frombuffer(data, dtype=np.uint8)
    ok = np.isin(arr, vals)
    run = 0
    for off in range(len(arr) - need + 1):
        if not ok[off]:
            continue
        blk = arr[off:off + need]
        if not ok[off:off + need].all():
            continue
        v2, c2 = np.unique(blk, return_counts=True)
        if dict(zip(v2.tolist(), c2.tolist())) == want:
            return off, blk
        run += 1
    return None, None


def main():
    levels_oc = np.repeat((np.arange(OC) - OC // 2)[:, None] * 2, IC, axis=1)
    levels_ic = np.repeat((np.arange(IC) - IC // 2)[None, :] * 2, OC, axis=0)

    data_a, qa = build("pq_oc", levels_oc)
    data_b, qb = build("pq_ic", levels_ic)

    off_a, blk_a = locate(data_a, qa)
    off_b, blk_b = locate(data_b, qb)
    if blk_a is None or blk_b is None:
        print("blob not found: A %s  B %s" % (off_a, off_b))
        return 1
    print("blob A at 0x%x, blob B at 0x%x, %d bytes each" % (off_a, off_b, IC * OC))

    oc_of = {int(qa[o, 0]) & 0xff: o for o in range(OC)}
    ic_of = {int(qb[0, i]) & 0xff: i for i in range(IC)}
    pos = [(oc_of.get(int(a)), ic_of.get(int(b))) for a, b in zip(blk_a, blk_b)]
    if any(p[0] is None or p[1] is None for p in pos):
        print("some bytes did not decode; levels collided")
        return 1

    addr = {}
    for i, (oc, ic) in enumerate(pos):
        addr[(oc, ic)] = i
    if len(addr) != IC * OC:
        print("the map is not a bijection: %d distinct pairs" % len(addr))
        return 1

    def ours(oc, ic):
        g, r = ic // A, ic % A
        return g * OC * A + oc * min(IC - g * A, A) + r

    def tiled(oc, ic):
        og, ig = oc // A, ic // A
        return (og * A * IC + ig * A * min(OC - og * A, A)
                + (oc % A) * min(IC - ig * A, A) + ic % A)

    def flat(oc, ic):
        return oc * IC + ic

    for name, f in (("mesa today  [ic/32][oc][ic%32]", ours),
                    ("tiled       [oc/32][ic/32][oc%32][ic%32]", tiled),
                    ("flat        [oc][ic]", flat)):
        bad = [(oc, ic) for (oc, ic), i in addr.items() if f(oc, ic) != i]
        print("%-42s %s" % (name, "MATCHES" if not bad
                            else "%d of %d wrong, first %s"
                            % (len(bad), IC * OC, sorted(bad)[:4])))

    print("\nfirst 8 addresses per (oc, ic), as the vendor placed them:")
    for oc in (0, 1, 31, 32, 33, 63):
        print("  oc %2d: " % oc
              + " ".join("ic%d->%d" % (ic, addr[(oc, ic)])
                         for ic in (0, 1, 31, 32, 33, 63)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
