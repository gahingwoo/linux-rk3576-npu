#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Read the vendor's 1x1 weight layout straight out of a compiled .rknn.

Round 7 left the pointwise convs as the only non-depthwise, non-first-conv case
that fails, and their regcmd now matches the vendor byte for byte apart from two
registers already shown inert and two requant fields that are not comparable
across differently quantized models. Their output is also constant across
different inputs, which is not what a merely mis-ordered weight buffer would
give, but the layout has never been checked against anything except a board
capture taken while the TASK_CON wall was still up, and the rule in this project
is to re-run anything from that era.

mesa packs a 1x1 conv as buf[oc*IC + ic] = w[oc][ic] - 0x80, IC*OC bytes, which
matches the DMA count in 0x101c. This gives every (oc, ic) pair a distinct weight
value, compiles it, finds the weight blob in the .rknn and reports which position
each byte came from. If the recovered order is oc-major with ic contiguous, mesa
is right and the bug is elsewhere.

Usage: posprobe_pw.py [ic] [oc]
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")

IC = int(sys.argv[1]) if len(sys.argv) > 1 else 16
OC = int(sys.argv[2]) if len(sys.argv) > 2 else 16
HW = 80

# One distinct level per (oc, ic). Symmetric int8 quantization keeps them
# distinct and monotone, which is all the probe needs.
levels = np.arange(IC * OC).reshape(OC, IC) - (IC * OC) // 2
w = (levels.astype(np.float32) / (IC * OC / 2.0)).reshape(OC, IC, 1, 1)

m = nn.Conv2d(IC, OC, 1, bias=True)
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w))
    m.bias.zero_()
m.eval()

os.makedirs(OUT, exist_ok=True)
onnx = f"{OUT}/pp_pw.onnx"
torch.onnx.export(m, torch.randn(1, IC, HW, HW), onnx,
                  input_names=["input"], output_names=["output"], opset_version=12)

calib = f"{OUT}/pp_pw_c.npy"
np.save(calib, (np.arange(IC * HW * HW).reshape(1, IC, HW, HW) % 251).astype(np.uint8))
ds = f"{OUT}/pp_pw_d.txt"
open(ds, "w").write(os.path.abspath(calib) + "\n")

from rknn.api import RKNN
r = RKNN(verbose=False)
r.config(target_platform="rk3576", quantized_method="layer")
assert r.load_onnx(model=onnx) == 0
assert r.build(do_quantization=True, dataset=ds) == 0
rk = f"{OUT}/pp_pw_rk3576.rknn"
assert r.export_rknn(rk) == 0
r.release()

# quantized_method="layer" keeps one scale for the whole tensor, so the
# monotone levels stay monotone and every (oc, ic) keeps a distinct byte.
scale = float(np.abs(w).max()) / 127.0
q = np.clip(np.round(w.reshape(OC, IC) / scale), -128, 127).astype(np.int8)
want = {}
for oc in range(OC):
    for ic in range(IC):
        want.setdefault(int(q[oc, ic]) & 0xff, []).append((oc, ic))
print(f"expecting {len(want)} distinct weight bytes out of {IC*OC} positions")

data = open(rk, "rb").read()
need = IC * OC
best = None
for off in range(len(data) - need):
    blk = data[off:off + need]
    if len(set(blk)) < need * 0.9:
        continue
    if sum(1 for b in blk if b in want) < need * 0.9:
        continue
    best = (off, blk)
    break

if best is None:
    print("no candidate weight blob found")
    sys.exit(1)

off, blk = best
print(f"weight blob at 0x{off:x}, {need} bytes, {len(set(blk))} distinct")
print("position of each byte, as (oc, ic):")
pos = []
for i, b in enumerate(blk):
    cands = want.get(b, [])
    pos.append(cands[0] if len(cands) == 1 else None)
for row in range(0, need, IC):
    line = " ".join(f"{p[0]:2d},{p[1]:2d}" if p else "  ?  "
                    for p in pos[row:row + IC])
    print(f"  [{row:4d}] {line}")

ocmajor = all(p == (i // IC, i % IC) for i, p in enumerate(pos) if p)
print(f"\noc-major with ic contiguous (what mesa emits): {ocmajor}")
