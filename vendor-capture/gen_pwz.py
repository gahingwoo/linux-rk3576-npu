#!/usr/bin/env python3
"""pwz: oc-CONSTANT pointwise, w[oc][ic]=ic-8 (ic-range -8..23 -> tensor zp~66,
oc-identical so A/B stay clean per-layer constants). Third B(zp) data point to
fix the bias-buffer coeff formula (pwka zp=0 B=128, pwkv zp=128 B=-127)."""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, 1, 1, 0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), np.float32)
for oc in range(OC):
    for ic in range(IC):
        w[oc, ic, 0, 0] = float(ic - 8)   # -8..23 over ic, same for all oc
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pwz.onnx", input_names=["input"], output_names=["output"], opset_version=12)
np.save("work/pwz.npy", np.random.rand(1, IC, HW, HW).astype(np.float32))
open("work/pwz.txt","w").write(os.path.abspath("work/pwz.npy")+"\n")
print("wrote work/pwz.onnx (w=ic-8, expect zp~66)")
