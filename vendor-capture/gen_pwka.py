#!/usr/bin/env python3
"""Asymmetric-weight pointwise (pwka): ic=32 oc=64 k1, weights ALL POSITIVE so
the per-tensor weight zero point is far from 128 (~33). Diff its vendor regcmd
against pwk (symmetric, zp~132) to isolate the weight-zero-point register."""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, 1, 1, 0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), np.float32)
for oc in range(OC):
    for ic in range(IC):
        w[oc, ic, 0, 0] = (ic + 1) * 1.0   # 1..32, all positive -> asymmetric zp
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pwka.onnx", input_names=["input"], output_names=["output"], opset_version=12)
calib = np.random.rand(1, IC, HW, HW).astype(np.float32)
npy = os.path.abspath("work/pwka.npy"); np.save(npy, calib); open("work/pwka.txt","w").write(npy+"\n")
print("wrote work/pwka.onnx")
