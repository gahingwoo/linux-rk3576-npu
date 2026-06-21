#!/usr/bin/env python3
"""pwb: pwka weights (zp=0, oc-const) but NONZERO per-oc bias = oc*100. Shows
where bias_q lands in the SDP bias buffer (A field of 0x5020, or the 0x5024 buffer)."""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, 1, 1, 0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), np.float32)
for oc in range(OC):
    for ic in range(IC):
        w[oc, ic, 0, 0] = float(ic + 1)        # same as pwka (zp=0)
b = np.array([oc*100.0 for oc in range(OC)], np.float32)  # nonzero per-oc bias
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.copy_(torch.from_numpy(b))
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pwb.onnx", input_names=["input"], output_names=["output"], opset_version=12)
np.save("work/pwb.npy", np.random.rand(1, IC, HW, HW).astype(np.float32))
open("work/pwb.txt","w").write(os.path.abspath("work/pwb.npy")+"\n")
print("wrote work/pwb.onnx (pwka weights + bias=oc*100)")
