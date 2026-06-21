#!/usr/bin/env python3
"""oc-VARYING asymmetric pointwise (pwkv): w[oc][ic] = (oc-30) (varies per oc,
constant over ic) -> per-oc weight sum differs so the bias-offset field steps
per channel (reveals the bias-buffer stride/grouping), and the tensor zp != 0,128
(confirms coeff = 0x80 - wt_zp)."""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, 1, 1, 0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), np.float32)
for oc in range(OC):
    w[oc, :, 0, 0] = float(oc - 30)     # -30..33, varies per oc
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pwkv.onnx", input_names=["input"], output_names=["output"], opset_version=12)
np.save("work/pwkv.npy", np.random.rand(1, IC, HW, HW).astype(np.float32))
open("work/pwkv.txt","w").write(os.path.abspath("work/pwkv.npy")+"\n")
print("wrote work/pwkv.onnx (w[oc]=oc-30)")
