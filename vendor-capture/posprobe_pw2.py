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


def locate(data, nlevels):
    """Find the IC*OC window holding each level exactly once per counterpart.

    Do not assume the byte values: rknn picks its own scale. The blob is the
    only window of IC*OC bytes carrying exactly `nlevels` distinct values with
    IC*OC/nlevels of each, which is a strong enough signature on its own.

    A neighbouring offset can carry the same multiset when the byte just
    outside happens to equal the one just inside, so every candidate is
    returned and the caller keeps the one that decodes.
    """
    need = IC * OC
    per = need // nlevels
    arr = np.frombuffer(data, dtype=np.uint8)
    onehot = np.zeros((256, len(arr) + 1), dtype=np.int32)
    onehot[arr, np.arange(len(arr))] = 1
    cs = onehot.cumsum(axis=1)
    hits = []
    for off in range(len(arr) - need + 1):
        c = cs[:, off + need] - cs[:, off]
        nz = c[c > 0]
        if nz.size == nlevels and (nz == per).all():
            hits.extend([off - 1, off, off + 1])
    return sorted({h for h in hits if 0 <= h <= len(arr) - need})


def main():
    levels_oc = np.repeat((np.arange(OC) - OC // 2)[:, None] * 2, IC, axis=1)
    levels_ic = np.repeat((np.arange(IC) - IC // 2)[None, :] * 2, OC, axis=0)

    data_a, _ = build("pq_oc", levels_oc)
    data_b, _ = build("pq_ic", levels_ic)

    cands = [o for o in locate(data_a, OC) if o in set(locate(data_b, IC))]
    addr = None
    for off in cands:
        a = np.frombuffer(data_a, dtype=np.uint8)[off:off + IC * OC].astype(np.int8)
        b = np.frombuffer(data_b, dtype=np.uint8)[off:off + IC * OC].astype(np.int8)
        if len(set(a.tolist())) != OC or len(set(b.tolist())) != IC:
            continue
        # the levels are monotone in the index, so sorting recovers it
        oc_of = {v: i for i, v in enumerate(sorted(set(a.tolist())))}
        ic_of = {v: i for i, v in enumerate(sorted(set(b.tolist())))}
        cand = {}
        for i, (x, y) in enumerate(zip(a.tolist(), b.tolist())):
            cand[(oc_of[x], ic_of[y])] = i
        if len(cand) == IC * OC:
            addr = cand
            print("blob at 0x%x, %d bytes" % (off, IC * OC))
            break
    if addr is None:
        print("blob not found; candidates %s" % ["0x%x" % c for c in cands[:8]])
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
