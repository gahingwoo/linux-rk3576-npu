# Isolation models to crack the per-channel SDP A/B/C requant formula.
# All conv2d-shaped (16->128,5x5,s2,SAME). Captured on the board -> A/B/C at bo01@51200.
import os, numpy as np, torch, torch.nn as nn
IC,OC,K,HW=16,128,5,80
os.makedirs("work",exist_ok=True)
def build(tag,w,b):
    m=nn.Conv2d(IC,OC,K,stride=2,padding=0,bias=True).eval()
    with torch.no_grad(): m.weight.copy_(torch.from_numpy(w.astype(np.float32))); m.bias.copy_(torch.from_numpy(b.astype(np.float32)))
    class M(nn.Module):
        def __init__(s): super().__init__(); s.c=m
        def forward(s,x): return s.c(nn.functional.pad(x,(1,2,1,2)))
    torch.onnx.export(M().eval(),torch.randn(1,IC,HW,HW),f"work/iso_{tag}.onnx",
                      input_names=["input"],output_names=["output"],opset_version=12)
    calib=(np.arange(IC*HW*HW)%251).astype(np.float32).reshape(1,IC,HW,HW)
    np.save(f"work/iso_{tag}_calib.npy",calib); open(f"work/iso_{tag}_ds.txt","w").write(os.path.abspath(f"work/iso_{tag}_calib.npy")+"\n")
    np.save(f"work/iso_{tag}_meta.npy",b)
    print(f"wrote iso_{tag}")

# M_scale: w[oc]=oc+1 constant within channel -> per-oc scale=(oc+1)/127, stored uniform 127,
#   sum uniform; ONLY per-channel scale varies. bias=0.
w=np.zeros((OC,IC,K,K)); 
for oc in range(OC): w[oc,:,:,:]=oc+1
build("scale", w, np.zeros(OC))

# M_sum: max magnitude fixed (100) but signed fraction varies -> per-oc weight SUM varies,
#   scale fixed. bias=0. flatten 400 weights: first f(oc) are +100, rest -100.
w=np.zeros((OC,IC,K,K))
for oc in range(OC):
    flat=np.full(IC*K*K,-100.0); npos=int(round((oc/127.0)*IC*K*K)); flat[:npos]=100.0
    w[oc]=flat.reshape(K,K,IC).transpose(2,0,1)
build("sum", w, np.zeros(OC))
