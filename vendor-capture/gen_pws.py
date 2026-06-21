#!/usr/bin/env python3
"""pws: SYMMETRIC weights w[oc][ic]=2*ic-31 (range -31..31 -> wt_zp~128 -> B~0),
oc-constant. Isolates the bias-buffer field A when the weight-zp term vanishes."""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, 1, 1, 0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), np.float32)
for oc in range(OC):
    for ic in range(IC):
        w[oc, ic, 0, 0] = float(2*ic - 31)   # -31..31 symmetric
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pws.onnx", input_names=["input"], output_names=["output"], opset_version=12)
np.save("work/pws.npy", np.random.rand(1, IC, HW, HW).astype(np.float32))
open("work/pws.txt","w").write(os.path.abspath("work/pws.npy")+"\n")
print("wrote work/pws.onnx (w=2ic-31 symmetric, expect zp~128 B~0)")
