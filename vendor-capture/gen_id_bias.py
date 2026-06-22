import os, numpy as np, torch, torch.nn as nn
IC,OC,K,HW=16,128,5,80
os.makedirs("work",exist_ok=True)
m=nn.Conv2d(IC,OC,K,stride=2,padding=0,bias=True).eval()
rng=np.random.RandomState(1)
wfix=rng.randint(-40,40,size=(IC,K,K)).astype(np.float32)   # SAME across oc
w=np.broadcast_to(wfix,(OC,IC,K,K)).copy()
b=(np.arange(OC)-64).astype(np.float32)*8.0                 # bias ramp, known
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.copy_(torch.from_numpy(b))
class M(nn.Module):
    def __init__(s): super().__init__(); s.c=m
    def forward(s,x): return s.c(nn.functional.pad(x,(1,2,1,2)))
mm=M().eval()
torch.onnx.export(mm,torch.randn(1,IC,HW,HW),"work/idb.onnx",input_names=["input"],output_names=["output"],opset_version=12)
calib=(np.arange(IC*HW*HW)%251).astype(np.float32).reshape(1,IC,HW,HW)
np.save("work/idb_calib.npy",calib); open("work/idb_ds.txt","w").write(os.path.abspath("work/idb_calib.npy")+"\n")
np.save("work/idb_bias.npy", b)
print("wrote work/idb.onnx, bias ramp (oc-64)*8")
