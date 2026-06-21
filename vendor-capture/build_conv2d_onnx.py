#!/usr/bin/env python3
"""
Build an ONNX conv that is the SAME conv as Mesa's conv2d.tflite: identical
shape (16->128, 5x5, stride 2, SAME pad, input 1x16x80x80) and identical weights
(the tflite's quantized weights dequantized to float). Converting THIS to .rknn
makes the vendor stack run provably the same conv as Mesa, from the one source
(conv2d.tflite) -- so the BO dumps can be diffed without wondering whether the
two models match.

The two toolkits re-quantize independently, so the final int8 *bytes* differ;
the comparison is therefore structural (BO size / layout / zero-padding /
histogram) + the raw input staging, which is what reveals a packing defect.
"""
import numpy as np
import torch
import torch.nn as nn

# conv2d.tflite quant constants (from parse_tflite.py)
W_SCALE, W_ZP = 3.9125464, 133          # weights uint8 per-tensor
B_SCALE = 0.03056677                    # bias int32 (= in_scale * w_scale)

# OHWI [128,5,5,16] uint8 -> dequant float
w_u8 = np.fromfile("conv2d_weights.i8", dtype=np.uint8).reshape(128, 5, 5, 16)
w_f = (w_u8.astype(np.float32) - W_ZP) * W_SCALE
# ONNX Conv wants OIHW: [128,16,5,5]
w_oihw = np.transpose(w_f, (0, 3, 1, 2)).copy()

b_i32 = np.frombuffer(open("conv2d_bias.i32", "rb").read(), dtype=np.int32)
b_f = b_i32.astype(np.float32) * B_SCALE


class M(nn.Module):
    def __init__(self):
        super().__init__()
        # SAME pad for 80->40, k5 s2 is asymmetric (1,2); torch can't do
        # asymmetric directly, so pad explicitly then conv with pad=0.
        self.c = nn.Conv2d(16, 128, kernel_size=5, stride=2, padding=0, bias=True)
        with torch.no_grad():
            self.c.weight.copy_(torch.from_numpy(w_oihw))
            self.c.bias.copy_(torch.from_numpy(b_f))

    def forward(self, x):
        x = nn.functional.pad(x, (1, 2, 1, 2))  # l,r,t,b  (SAME for k5 s2)
        return self.c(x)


m = M().eval()
x = torch.randn(1, 16, 80, 80)
torch.onnx.export(m, x, "conv2d.onnx", input_names=["input"],
                  output_names=["output"], opset_version=12)
print("wrote conv2d.onnx  (16->128 k5 s2 SAME, weights from conv2d.tflite)")

# Calibration dataset for RKNN activation quant (weights quant is data-free).
os_dir = "work"
import os
os.makedirs(os_dir, exist_ok=True)
calib = (np.arange(1 * 80 * 80 * 16) % 251).astype(np.uint8).reshape(1, 80, 80, 16)
np.save(f"{os_dir}/conv2d_calib.npy", calib)
with open(f"{os_dir}/conv2d_ds.txt", "w") as f:
    f.write(f"{os_dir}/conv2d_calib.npy\n")
print(f"wrote {os_dir}/conv2d_calib.npy + {os_dir}/conv2d_ds.txt")
