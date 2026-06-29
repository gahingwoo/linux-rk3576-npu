#!/usr/bin/env python3
# Depthwise conv matching MobileNet v1 dw1: 32ch, 3x3, stride 1, SAME pad,
# input 1x32x112x112. Convert -> RK3576 rknn (do_quantization=True -> vendor
# uint8 per-tensor, MobileNet's regime) -> extract the vendor depthwise regcmd
# to diff vs mesa's depthwise regcmd (the CONV/CORE config, never verified).
import numpy as np, torch, torch.nn as nn
C, HW = 32, 112
class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.c = nn.Conv2d(C, C, 3, stride=1, padding=1, groups=C, bias=True)  # groups=C = depthwise
        rng = np.random.RandomState(0)
        with torch.no_grad():
            self.c.weight.copy_(torch.from_numpy((rng.randn(C, 1, 3, 3) * 0.1).astype(np.float32)))
            self.c.bias.copy_(torch.from_numpy((rng.randn(C) * 0.05).astype(np.float32)))
    def forward(self, x):
        return self.c(x)
m = M().eval()
x = torch.randn(1, C, HW, HW)
torch.onnx.export(m, x, "dw.onnx", input_names=["input"], output_names=["output"], opset_version=12)
print("wrote dw.onnx")
# calib: NCHW uint8
calib = (np.arange(1 * C * HW * HW).reshape(1, C, HW, HW) % 251).astype(np.uint8)
np.save("dw_calib.npy", calib)
open("dw_dataset.txt", "w").write("dw_calib.npy\n")
print("wrote dw_calib.npy + dw_dataset.txt", calib.shape)
