#!/usr/bin/env python3
"""
Parameterized single-Conv2d ONNX generator for differential register mapping.
Usage: gen.py <tag> in=3 out=32 k=3 s=2 p=1 hw=224
Writes work/<tag>.onnx and a matching calib npy + dataset txt.
"""
import sys, os
import numpy as np
import torch, torch.nn as nn

def kv(args):
    d = {"in": 3, "out": 32, "k": 3, "s": 2, "p": 1, "hw": 224, "g": 1}
    for a in args:
        key, val = a.split("=")
        d[key] = int(val)
    return d

class M(nn.Module):
    def __init__(self, ci, co, k, s, p, g):
        super().__init__()
        self.c = nn.Conv2d(ci, co, kernel_size=k, stride=s, padding=p,
                           groups=g, bias=True)
    def forward(self, x):
        return self.c(x)

def main():
    tag = sys.argv[1]
    d = kv(sys.argv[2:])
    os.makedirs("work", exist_ok=True)
    m = M(d["in"], d["out"], d["k"], d["s"], d["p"], d["g"]).eval()
    x = torch.randn(1, d["in"], d["hw"], d["hw"])
    onnx = f"work/{tag}.onnx"
    torch.onnx.export(m, x, onnx, input_names=["input"],
                      output_names=["output"], opset_version=12)
    calib = np.random.rand(1, d["in"], d["hw"], d["hw"]).astype(np.float32)
    npy = os.path.abspath(f"work/{tag}.npy")
    np.save(npy, calib)
    with open(f"work/{tag}.txt", "w") as f:
        f.write(npy + "\n")
    print(f"wrote {onnx}  params={d}")

if __name__ == "__main__":
    main()
