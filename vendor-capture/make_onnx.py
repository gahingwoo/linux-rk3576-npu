#!/usr/bin/env python3
"""
Export a single Conv2d to ONNX, matching MobileNetV1's first conv that fails to
engage on RK3576: in=3, out=32, 3x3, stride 2, pad 1, input 1x3x224x224. One conv
is enough to capture how the vendor arms/starts the CNA on rk3576.
"""
import torch, torch.nn as nn

class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.c = nn.Conv2d(3, 32, kernel_size=3, stride=2, padding=1, bias=True)
    def forward(self, x):
        return self.c(x)

m = M().eval()
x = torch.randn(1, 3, 224, 224)
torch.onnx.export(m, x, "conv0.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)
print("wrote conv0.onnx")
