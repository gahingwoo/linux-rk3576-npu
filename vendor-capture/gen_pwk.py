#!/usr/bin/env python3
"""
Identifiable POINTWISE (1x1) conv for decoding the RK3576 normal-conv weight
layout. ic=32 oc=64 k1 s1 (= MobileNet conv_pw_1 shape). Weight encodes its own
(oc,ic): w[oc][ic] = (ic-16)*6 + sign(oc)  -> the stored byte tracks ic (varies
per input channel, ~constant across oc) so the buffer's ic-ordering is readable;
a small per-oc tilt lets the oc-blocking show. Per-tensor quant (mobilenet-style).
"""
import os, numpy as np, torch, torch.nn as nn
IC, OC, HW = 32, 64, 112
os.makedirs("work", exist_ok=True)
m = nn.Conv2d(IC, OC, kernel_size=1, stride=1, padding=0, bias=True).eval()
w = np.zeros((OC, IC, 1, 1), dtype=np.float32)
for oc in range(OC):
    for ic in range(IC):
        w[oc, ic, 0, 0] = (ic - 16) * 6.0 + (1.0 if (oc % 2) else -1.0)
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/pwk.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)
calib = np.random.rand(1, IC, HW, HW).astype(np.float32)
npy = os.path.abspath("work/pwk.npy"); np.save(npy, calib)
open("work/pwk.txt","w").write(npy+"\n")
print("wrote work/pwk.onnx  ic=32 oc=64 k1 s1 hw112")
