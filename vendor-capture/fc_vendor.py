#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Compile the vendor's own MobileNet first conv and diff its registers against
the ones rkt_regcmd.c hardcodes.

conv0 has never passed. The logs of 2026-08-08 and 2026-08-09 show the same
0 of 32, so it predates every change made this week; it was simply never in the
regression set being run. It takes its own code path, fill_regcmd_firstconv,
whose values are literals taken from one capture, and literals taken from one
capture are exactly what CNA 0x1080 and DPU 0x4050 both turned out to be wrong
about.

Same method that settled the depthwise weight layout and 0x4050: compile the
geometry with the toolkit, pull the register stream out of the .rknn, compare.
No board.
"""
import os
import struct
import sys

import numpy as np

from extract_regcmd import TARGETS, decode

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geom")


def build(name, ic=3, oc=32, hw=224, k=3, stride=2):
    import torch
    import torch.nn as nn
    from rknn.api import RKNN

    os.makedirs(OUT, exist_ok=True)
    onnx, out = f"{OUT}/{name}.onnx", f"{OUT}/{name}_rk3576.rknn"
    rng = np.random.RandomState(3)
    w = (rng.randn(oc, ic, k, k) * 0.08).astype(np.float32)
    b = (rng.randn(oc) * 0.05).astype(np.float32)
    m = nn.Conv2d(ic, oc, k, stride=stride, padding=k // 2, bias=True)
    with torch.no_grad():
        m.weight.copy_(torch.from_numpy(w))
        m.bias.copy_(torch.from_numpy(b))
    m.eval()
    torch.onnx.export(m, torch.randn(1, ic, hw, hw), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)
    calib = f"{OUT}/{name}_c.npy"
    np.save(calib,
            (np.arange(ic * hw * hw).reshape(1, ic, hw, hw) % 251).astype(np.uint8))
    ds = f"{OUT}/{name}_d.txt"
    open(ds, "w").write(os.path.abspath(calib) + "\n")
    r = RKNN(verbose=False)
    r.config(target_platform="rk3576", compress_weight=False)
    assert r.load_onnx(model=onnx) == 0
    assert r.build(do_quantization=True, dataset=ds) == 0
    assert r.export_rknn(out) == 0
    r.release()
    print(f"OK {name}: {ic} in, {oc} out, {hw}x{hw}, k{k} s{stride}")
    return out


def regs(path):
    d = open(path, "rb").read()
    n = len(d) // 8
    w = struct.unpack("<%dQ" % n, d[:n * 8])
    runs, i = [], 0
    while i < n:
        if ((w[i] >> 48) & 0xffff) in TARGETS:
            j = i
            while j < n and ((w[j] >> 48) & 0xffff) in TARGETS:
                j += 1
            if j - i >= 40:
                runs.append([decode(w[k]) for k in range(i, j)])
            i = j
        else:
            i += 1
    out = []
    for r in runs:
        m = {}
        for t, v, reg in r:
            m.setdefault(reg, v)
        out.append(m)
    return out


# What fill_regcmd_firstconv writes as literals.
MESA = {0x101c: 0x00000600, 0x1020: 0x00000030, 0x1024: 0x0202001f,
        0x1028: 0x0d20000b, 0x102c: 0x00df00df, 0x1030: 0x0060006f,
        0x1034: 0x000030ff, 0x1038: 0x00000007, 0x103c: 0x000f0000,
        0x1040: 0x10000000, 0x1044: 0x00e0000f, 0x1048: 0x000e38e0,
        0x104c: 0x40004000, 0x1050: 0x00014000, 0x1080: 0x00000101,
        0x1084: 0x00808080, 0x108c: 0x000f000f, 0x1090: 0x0000002a,
        0x1094: 0x000024c0, 0x1098: 0x000024c0, 0x4060: 0x00000903,
        0x40b8: 0x00003100}


if __name__ == "__main__":
    p = f"{OUT}/fc_224_rk3576.rknn"
    if not os.path.exists(p):
        build("fc_224")
    rs = regs(p)
    print(f"\n{len(rs)} tasks in the vendor's first conv")
    v = rs[0]
    print(f"\n{'reg':>8} {'mesa hardcodes':>18} {'vendor task0':>18}  verdict")
    bad = []
    for reg in sorted(MESA):
        got = v.get(reg)
        ok = got == MESA[reg]
        if not ok:
            bad.append(reg)
        shown = f"{got:#010x}" if got is not None else "absent"
        print(f"  0x{reg:04x} {MESA[reg]:#018x} {shown:>18}  "
              f"{'ok' if ok else 'DIFFERS'}")
    print(f"\n{len(bad)} of {len(MESA)} hardcoded values differ: "
          + ", ".join(f"0x{r:04x}" for r in bad))
