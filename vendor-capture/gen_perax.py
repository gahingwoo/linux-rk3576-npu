import os, numpy as np, torch, torch.nn as nn
from rknn.api import RKNN
SCR=os.path.dirname(os.path.abspath(__file__))
IC=OC=16*1  # use IC=16, OC=128 for pointwise to match conv2d feature atom
ICp, OCp = 16, 128

def export(tag, model, x, w):
    onnx=f"{SCR}/{tag}.onnx"
    torch.onnx.export(model, x, onnx, input_names=["input"], output_names=["output"], opset_version=12)
    np.save(f"{SCR}/{tag}_w.npy", w)
    calib=(np.arange(int(np.prod(x.shape)))%251).astype(np.float32).reshape(tuple(x.shape))
    np.save(f"{SCR}/{tag}_calib.npy", calib)
    open(f"{SCR}/{tag}_ds.txt","w").write(f"{SCR}/{tag}_calib.npy\n")
    r=RKNN(verbose=False)
    r.config(target_platform="rk3576", quantized_dtype="w8a8", quantized_method="channel")
    assert r.load_onnx(model=onnx)==0
    assert r.build(do_quantization=True, dataset=f"{SCR}/{tag}_ds.txt")==0
    assert r.export_rknn(f"{SCR}/{tag}.rknn")==0
    r.release()
    print(f"  wrote {tag}.rknn  w.shape={w.shape}")

# pw_ic: 1x1 pointwise, weight[oc,ic]=ic+1
w=np.zeros((OCp,ICp,1,1),np.float32)
for oc in range(OCp):
    for ic in range(ICp): w[oc,ic,0,0]=ic+1
class PW(nn.Module):
    def __init__(s,w):
        super().__init__(); s.c=nn.Conv2d(ICp,OCp,1,bias=False)
        with torch.no_grad(): s.c.weight.copy_(torch.from_numpy(w))
    def forward(s,x): return s.c(x)
export("pw_ic", PW(w).eval(), torch.randn(1,ICp,8,8), w)

# pw_oc: weight[oc,ic]=oc+1
w2=np.zeros((OCp,ICp,1,1),np.float32)
for oc in range(OCp):
    for ic in range(ICp): w2[oc,ic,0,0]=oc+1
export("pw_oc", PW(w2).eval(), torch.randn(1,ICp,8,8), w2)

# dw_k: 3x3 depthwise, weight[c,ky,kx]=ky*3+kx+1
C=16
wd=np.zeros((C,1,3,3),np.float32)
for c in range(C):
    for ky in range(3):
        for kx in range(3): wd[c,0,ky,kx]=ky*3+kx+1
class DW(nn.Module):
    def __init__(s,w):
        super().__init__(); s.c=nn.Conv2d(C,C,3,padding=1,groups=C,bias=False)
        with torch.no_grad(): s.c.weight.copy_(torch.from_numpy(w))
    def forward(s,x): return s.c(x)
export("dw_k", DW(wd).eval(), torch.randn(1,C,8,8), wd)
print("DONE")
