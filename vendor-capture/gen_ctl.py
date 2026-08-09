# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
import os, sys, numpy as np, torch, torch.nn as nn
OC,IC,K = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
tag=sys.argv[4]; mode=sys.argv[5] if len(sys.argv)>5 else "occonst"
HW=8
os.makedirs("work",exist_ok=True)
w=np.zeros((OC,IC,K,K),np.float32)
if mode=="occonst":
    for oc in range(OC): w[oc,:,:,:]=(oc+1)*0.05
elif mode=="ramp":
    w=(np.arange(OC*IC*K*K)%120-60).astype(np.float32).reshape(OC,IC,K,K)*0.03
elif mode=="single":
    for oc in range(OC):
        idx=oc%(IC*K*K); w.reshape(OC,-1)[oc,idx]=1.0
b=np.zeros(OC,np.float32)
if mode=="occonst": b=(np.arange(OC)).astype(np.float32)*0.1
class M(nn.Module):
    def __init__(s):
        super().__init__(); s.c=nn.Conv2d(IC,OC,K,1,1,bias=True)
        with torch.no_grad(): s.c.weight.copy_(torch.from_numpy(w)); s.c.bias.copy_(torch.from_numpy(b))
    def forward(s,x): return s.c(x)
m=M().eval(); x=torch.randn(1,IC,HW,HW)
onnx=f"work/c_{tag}.onnx"
torch.onnx.export(m,x,onnx,input_names=["input"],output_names=["output"],opset_version=12)
lines=[]
for i in range(8):
    s=(np.random.RandomState(i).randn(1,IC,HW,HW)*0.3).astype(np.float32)
    p=os.path.abspath(f"work/c_{tag}_cal{i}.npy"); np.save(p,s); lines.append(p)
open(f"work/c_{tag}_ds.txt","w").write("\n".join(lines)+"\n")
np.save(f"work/c_{tag}_w.npy",w); np.save(f"work/c_{tag}_b.npy",b)
print(f"{tag}: OC={OC} IC={IC} K={K} mode={mode} w[:,0,0,0]={w[:,0,0,0]} b={b}")
