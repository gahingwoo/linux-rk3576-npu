import os, numpy as np, torch, torch.nn as nn
from rknn.api import RKNN
SCR = os.path.dirname(os.path.abspath(__file__))
# conv2d's EXACT shape: OC=128, IC=16, KH=KW=5, per-tensor
OC, IC, KH, KW, HW = 128, 16, 5, 5, 12

def build(tag, weight_oihw, bias):
    class M(nn.Module):
        def __init__(s):
            super().__init__(); s.c = nn.Conv2d(IC, OC, KH, bias=True, padding=2)
            with torch.no_grad():
                s.c.weight.copy_(torch.from_numpy(weight_oihw))
                s.c.bias.copy_(torch.from_numpy(bias))
        def forward(s, x): return s.c(x)
    m = M().eval()
    onnx = f"{SCR}/{tag}.onnx"
    torch.onnx.export(m, torch.randn(1, IC, HW, HW), onnx,
                      input_names=["input"], output_names=["output"], opset_version=12)
    calib = (np.arange(1*IC*HW*HW) % 251).astype(np.float32).reshape(1, IC, HW, HW)
    np.save(f"{SCR}/posprobe_calib.npy", calib)
    open(f"{SCR}/posprobe_ds.txt", "w").write(f"{SCR}/posprobe_calib.npy\n")
    r = RKNN(verbose=False)
    r.config(target_platform="rk3576", quantized_dtype="w8a8", quantized_method="layer")  # per-TENSOR
    assert r.load_onnx(model=onnx) == 0
    assert r.build(do_quantization=True, dataset=f"{SCR}/posprobe_ds.txt") == 0
    assert r.export_rknn(f"{SCR}/{tag}.rknn") == 0
    r.release()
    print(f"OK wrote {tag}.rknn  shape OIHW={weight_oihw.shape} per-tensor")

# probe_a: position RAMP. lin = OIHW linear index; value cycles every 253 (coprime spread via *37)
lin = np.arange(OC*IC*KH*KW)
val_a = (((lin*37) % 251) - 125).astype(np.float32) / 64.0   # ~[-1.95,1.95], per-tensor
w_a = val_a.reshape(OC, IC, KH, KW)
# probe_b: a SECOND no-zero ramp, multiplier 53 (same uniform no-zero distribution as a,
# different value-per-position). Decisive test = decode each weight slot to OIHW lin in a
# (*37) and b (*53); same slot -> same lin = position-fixed = derivable. (gaussian b was a
# bad control: near-zeros confound a mask compare; the *53 ramp tests positions directly.)
val_b = (((lin*53) % 251) - 125).astype(np.float32) / 64.0
w_b = val_b.reshape(OC, IC, KH, KW)
bias = np.zeros(OC, np.float32)
build("posprobe_a", w_a, bias)
build("posprobe_b", w_b, bias)
# save the ramp weights so the decoder can recover placement if mask is position-fixed
np.save(f"{SCR}/posprobe_a_w.npy", w_a)
print("done")
