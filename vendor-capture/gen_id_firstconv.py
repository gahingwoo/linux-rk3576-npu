#!/usr/bin/env python3
"""
Identifiable FIRSTCONV generator for decoding the RK3576 first-conv weight-buffer
layout (the conv0 that ends up distinct=2 / MAC=0 because mesa packs the generic
RK3588 18432-byte layout while the CNA reads a 1536-byte first-conv layout).

conv0 shape: in=3, out=32, k=3x3, stride=2, pad=1, input 1x3x224x224 (MobileNetV1
first conv). Weights encode their own (oc, ic, ky, kx) position:

    w[oc][ic][ky][kx] = (oc + 1) * (ic*9 + ky*3 + kx + 1)

The inner factor P = ic*9 + ky*3 + kx + 1 takes 27 distinct values 1..27 over the
3 input channels x 3x3 kernel. After per-output-channel symmetric int8 quant the
per-oc (oc+1) factor cancels, so every oc block stores the SAME 27-value pattern
   round(P / 27 * 127)  for P=1..27
and each stored byte's value -> its rank -> P -> (ic, ky, kx); the byte's POSITION
in the 48-byte oc block -> the packing slot. The (oc+1) factor also makes the
per-oc scale grow monotonically, confirming oc-major ordering. Pad/alpha bytes are
the weight zero-point (0 here), distinct from the 5..127 position values.
"""
import os, numpy as np, torch, torch.nn as nn

IC = 3; OC = 32; K = 3; H = W = 224
os.makedirs("work", exist_ok=True)

m = nn.Conv2d(IC, OC, kernel_size=K, stride=2, padding=1, bias=True).eval()
w = np.zeros((OC, IC, K, K), dtype=np.float32)
for oc in range(OC):
    for ic in range(IC):
        for ky in range(K):
            for kx in range(K):
                # No per-oc factor: the toolkit quantizes this single conv
                # per-TENSOR, so a per-oc scale would crush low channels. Keep
                # every oc identical -> every 48-byte oc block stores the same
                # clean P=1..27 pattern, decodable regardless of quant scheme.
                w[oc, ic, ky, kx] = ic * 9 + ky * 3 + kx + 1
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w))
    m.bias.zero_()

x = torch.randn(1, IC, H, W)
torch.onnx.export(m, x, "work/fck.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)

calib = np.random.rand(1, IC, H, W).astype(np.float32)
npy = os.path.abspath("work/fck.npy")
np.save(npy, calib)
open("work/fck.txt", "w").write(npy + "\n")

pat = np.array([p + 1 for p in range(27)], dtype=np.float32)
q = np.round(pat / pat.max() * 127).astype(int)
print("wrote work/fck.onnx  in=3 out=32 k3 s2 hw224")
print("expected per-oc int8 pattern P=1..27 (ic*9+ky*3+kx+1):")
print(" ", list(q))
print("decode: byte value -> index in this list -> P-1 -> ic=P//9, ky=(P%9)//3, kx=P%3")
