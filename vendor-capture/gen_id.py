#!/usr/bin/env python3
"""
Identifiable depthwise generator for decoding the RK3576 weight-buffer layout.
Builds conv_dw_1 shape (ic=oc=32, g=32, k3, s1, p1, hw112) with KNOWN weights:
    w[c][ky][kx] = (c+1) * (ky*3+kx+1)
After per-channel symmetric int8 quant the stored weight bytes become
channel-independent: round((ky*3+kx+1)/9*127) -> the 9 distinct values
   [14,28,42,57,71,85,99,113,127]
so each captured byte reveals its (ky,kx); the per-channel scale (c+1)*9/127
grows monotonically with c, so any per-channel field in the buffer reveals c.
"""
import os, numpy as np, torch, torch.nn as nn

IC = 32; K = 3; HW = 112
os.makedirs("work", exist_ok=True)

m = nn.Conv2d(IC, IC, kernel_size=K, stride=1, padding=1, groups=IC, bias=True).eval()
w = np.zeros((IC, 1, K, K), dtype=np.float32)
for c in range(IC):
    for ky in range(K):
        for kx in range(K):
            w[c, 0, ky, kx] = (c + 1) * (ky * 3 + kx + 1)
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w))
    m.bias.zero_()

x = torch.randn(1, IC, HW, HW)
torch.onnx.export(m, x, "work/dwk.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)

calib = np.random.rand(1, IC, HW, HW).astype(np.float32)
npy = os.path.abspath("work/dwk.npy")
np.save(npy, calib)
open("work/dwk.txt", "w").write(npy + "\n")

# Show the expected channel-independent stored int8 pattern.
pat = np.array([(p + 1) for p in range(9)], dtype=np.float32)
q = np.round(pat / pat.max() * 127).astype(int)
print("wrote work/dwk.onnx  ic=oc=32 g=32 k3 s1 hw112")
print("expected weight int8 per (ky,kx) p=0..8:", list(q))
