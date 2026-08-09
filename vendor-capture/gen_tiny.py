# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
import os, sys, numpy as np, torch, torch.nn as nn
OC,IC,K,HW = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), 8
tag=sys.argv[4]
os.makedirs("work",exist_ok=True)
rng=np.random.default_rng(0)
w=rng.integers(-60,60,size=(OC,IC,K,K)).astype(np.float32)*0.03
class M(nn.Module):
    def __init__(s):
        super().__init__(); s.c=nn.Conv2d(IC,OC,K,stride=1,padding=1,bias=True)
        with torch.no_grad(): s.c.weight.copy_(torch.from_numpy(w)); s.c.bias.zero_()
    def forward(s,x): return s.c(x)
m=M().eval(); x=torch.randn(1,IC,HW,HW)
onnx=f"work/tiny_{tag}.onnx"
torch.onnx.export(m,x,onnx,input_names=["input"],output_names=["output"],opset_version=12)
calib=(np.arange(IC*HW*HW)%251).astype(np.float32).reshape(1,IC,HW,HW)
npy=os.path.abspath(f"work/tiny_{tag}_calib.npy"); np.save(npy,calib)
open(f"work/tiny_{tag}_ds.txt","w").write(npy+"\n")
print(f"wrote {onnx} OC={OC} IC={IC} K={K}")
