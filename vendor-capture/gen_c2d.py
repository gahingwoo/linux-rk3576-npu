import os,sys,numpy as np,torch,torch.nn as nn
# conv2d-shaped controlled conv: IC=16 OC=128 K=5 stride2 pad SAME-ish, HW=80
tag=sys.argv[1]; mode=sys.argv[2]
IC,OC,K,HW=16,128,5,80
os.makedirs("work",exist_ok=True)
rng=np.random.RandomState(7)
w=np.zeros((OC,IC,K,K),np.float32); b=np.zeros(OC,np.float32)
if mode=="occonst":            # weights per-oc constant value, bias 0
    for oc in range(OC): w[oc]=((oc%50)-25)*0.05
elif mode=="biasramp":         # weights random fixed, bias = per-oc ramp
    w=(rng.randint(-60,60,(OC,IC,K,K))*0.03).astype(np.float32)
    b=((np.arange(OC)-64)*0.02).astype(np.float32)
elif mode=="rand":             # like conv2d
    w=(rng.randint(-60,60,(OC,IC,K,K))*0.03).astype(np.float32)
np.save(f"work/{tag}_w.npy",w); np.save(f"work/{tag}_b.npy",b)
class M(nn.Module):
    def __init__(s):
        super().__init__(); s.c=nn.Conv2d(IC,OC,K,stride=2,padding=2,bias=True)
        with torch.no_grad(): s.c.weight.copy_(torch.from_numpy(w)); s.c.bias.copy_(torch.from_numpy(b))
    def forward(s,x): return s.c(x)
m=M().eval()
torch.onnx.export(m,torch.randn(1,IC,HW,HW),f"work/{tag}.onnx",
    input_names=["input"],output_names=["output"],opset_version=12)
lines=[]
for i in range(10):
    s=(np.random.RandomState(i).randn(1,IC,HW,HW)*0.3).astype(np.float32)
    p=os.path.abspath(f"work/{tag}_c{i}.npy"); np.save(p,s); lines.append(p)
open(f"work/{tag}_ds.txt","w").write("\n".join(lines)+"\n")
print(f"{tag} mode={mode} w[:,0,0,0][:6]={w[:6,0,0,0]} b[:6]={b[:6]}")
