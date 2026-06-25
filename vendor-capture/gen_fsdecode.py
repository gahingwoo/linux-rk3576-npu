import os, numpy as np, torch, torch.nn as nn
from rknn.api import RKNN
SCR=os.path.dirname(os.path.abspath(__file__))
ICp, OCp = 16, 128
def export(tag, w, b, method="channel"):
    class M(nn.Module):
        def __init__(s):
            super().__init__(); s.c=nn.Conv2d(ICp,OCp,1,bias=(b is not None))
            with torch.no_grad():
                s.c.weight.copy_(torch.from_numpy(w))
                if b is not None: s.c.bias.copy_(torch.from_numpy(b))
        def forward(s,x): return s.c(x)
    m=M().eval(); x=torch.randn(1,ICp,8,8)
    onnx=f"{SCR}/{tag}.onnx"
    torch.onnx.export(m,x,onnx,input_names=["input"],output_names=["output"],opset_version=12)
    np.save(f"{SCR}/{tag}_w.npy",w); 
    if b is not None: np.save(f"{SCR}/{tag}_b.npy",b)
    calib=(np.arange(1*ICp*8*8)%251).astype(np.float32).reshape(1,ICp,8,8)
    np.save(f"{SCR}/{tag}_calib.npy",calib); open(f"{SCR}/{tag}_ds.txt","w").write(f"{SCR}/{tag}_calib.npy\n")
    r=RKNN(verbose=False)
    r.config(target_platform="rk3576", quantized_dtype="w8a8", quantized_method=method)
    assert r.load_onnx(model=onnx)==0
    assert r.build(do_quantization=True, dataset=f"{SCR}/{tag}_ds.txt")==0
    assert r.export_rknn(f"{SCR}/{tag}.rknn")==0
    r.release(); print(f"  wrote {tag}.rknn method={method}")

# g_bias: const weight, bias ramp
w=np.full((OCp,ICp,1,1),64.0,np.float32)
b=((np.arange(OCp)+1)*100.0).astype(np.float32)
export("g_bias", w, b)
# g_const: const weight, no bias (baseline)
export("g_const", np.full((OCp,ICp,1,1),64.0,np.float32), None)
# g_pt: weight=oc+1 but PER-TENSOR (method=layer)
w2=np.zeros((OCp,ICp,1,1),np.float32)
for oc in range(OCp): w2[oc,:,0,0]=oc+1
export("g_pt", w2, None, method="layer")
print("DONE")
