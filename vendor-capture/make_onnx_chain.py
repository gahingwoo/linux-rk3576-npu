#!/usr/bin/env python3
"""
MobileNetV1 head: conv0 -> dw1 -> pw1 (-> dw2), exported to ONNX so the toolkit
compiles them IN-GRAPH. dw1/pw1 are then middle layers (real depthwise/pointwise
encoder path + real input context = conv0's output), not a standalone first conv.
Weights are random (re-quantized by the toolkit), so OUT_CVT is approximate, but
the per-layer GEOMETRY / CBUF / FC_CON1 / surface config is shape-driven and
matches the real model -- that's what we diff against mesa.
"""
import torch, torch.nn as nn

class Head(nn.Module):
    def __init__(self):
        super().__init__()
        # conv0: 3->32, 3x3 s2 p1   (input 224x224 -> 112x112)
        self.conv0 = nn.Conv2d(3, 32, 3, stride=2, padding=1, bias=True)
        self.relu0 = nn.ReLU6()
        # dw1: depthwise 32, 3x3 s1 p1  (112x112)
        self.dw1 = nn.Conv2d(32, 32, 3, stride=1, padding=1, groups=32, bias=True)
        self.relud1 = nn.ReLU6()
        # pw1: pointwise 32->64, 1x1 s1
        self.pw1 = nn.Conv2d(32, 64, 1, stride=1, padding=0, bias=True)
        self.relup1 = nn.ReLU6()
        # dw2: depthwise 64, 3x3 s2 p1 (112 -> 56)
        self.dw2 = nn.Conv2d(64, 64, 3, stride=2, padding=1, groups=64, bias=True)
        self.relud2 = nn.ReLU6()

    def forward(self, x):
        x = self.relu0(self.conv0(x))
        x = self.relud1(self.dw1(x))
        x = self.relup1(self.pw1(x))
        x = self.relud2(self.dw2(x))
        return x

m = Head().eval()
x = torch.randn(1, 3, 224, 224)
torch.onnx.export(m, x, "chain.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)
print("wrote chain.onnx (conv0->dw1->pw1->dw2)")
