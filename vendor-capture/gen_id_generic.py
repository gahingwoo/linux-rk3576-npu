#!/usr/bin/env python3
"""
Identifiable GENERIC-conv generator for decoding the RK3576 generic weight-buffer
layout — the one Mesa's rkt_fill_weights still packs in the RK3588 order
(rkt_coefs.c:204+) for any conv that isn't first-conv / pointwise / depthwise, so
conv2d (16->128, 5x5) gets garbage-ordered weights and goes degenerate while the
vendor's compact RK3576 packing computes (proven by the cross-UABI replay).

conv2d shape (== build_conv2d_onnx.py / Mesa's conv2d.tflite): in=16, out=128,
k=5x5, stride=2, SAME pad, input 1x16x80x80.

A weight is w[oc][ic][ky][kx], oc 0..127, ic 0..15, ky 0..4, kx 0..4 — 51200 of
them. 8-bit int8 can't carry a unique index for all 400 inner (ic,ky,kx) slots,
so we split the position across THREE captures, each encoding ONE group so its
quantized byte value decodes (by rank) to that coordinate, independent of the
others (every other coordinate held constant -> per-tensor quant maps each input
value to a fixed byte):

    A  w = ky*5 + kx + 1        (1..25)   captured byte -> (ky, kx)
    B  w = ic + 1               (1..16)   captured byte -> ic
    C  w = oc + 1               (1..128)  captured byte -> oc

Capture all three vendor weight buffers, then for output byte position N:
    oc_N = rank(C[N]), ic_N = rank(B[N]), (ky_N,kx_N) = rank(A[N])
gives the full (oc,ic,ky,kx) that lives at slot N — the RK3576 generic packing
permutation to implement in mesa. Pad/zero slots read the weight zero-point in
all three and decode to no real position.
"""
import os
import numpy as np
import torch
import torch.nn as nn

IC, OC, K, HW = 16, 128, 5, 80
os.makedirs("work", exist_ok=True)


def build(tag, fill):
    """fill(oc,ic,ky,kx) -> float weight; export ONNX + a calib set."""
    w = np.zeros((OC, IC, K, K), dtype=np.float32)
    for oc in range(OC):
        for ic in range(IC):
            for ky in range(K):
                for kx in range(K):
                    w[oc, ic, ky, kx] = fill(oc, ic, ky, kx)

    class M(nn.Module):
        def __init__(self):
            super().__init__()
            self.c = nn.Conv2d(IC, OC, kernel_size=K, stride=2, padding=0, bias=True)
            with torch.no_grad():
                self.c.weight.copy_(torch.from_numpy(w))
                self.c.bias.zero_()

        def forward(self, x):
            x = nn.functional.pad(x, (1, 2, 1, 2))  # SAME for k5 s2
            return self.c(x)

    m = M().eval()
    x = torch.randn(1, IC, HW, HW)
    onnx = f"work/idg_{tag}.onnx"
    torch.onnx.export(m, x, onnx, input_names=["input"],
                      output_names=["output"], opset_version=12)
    calib = (np.arange(1 * IC * HW * HW) % 251).astype(np.float32).reshape(1, IC, HW, HW)
    npy = os.path.abspath(f"work/idg_{tag}_calib.npy")
    np.save(npy, calib)
    open(f"work/idg_{tag}_ds.txt", "w").write(npy + "\n")
    print(f"wrote {onnx}  (+ calib)  [{tag}]")


build("A", lambda oc, ic, ky, kx: ky * 5 + kx + 1)   # -> (ky,kx)  1..25
build("B", lambda oc, ic, ky, kx: ic + 1)            # -> ic       1..16
build("C", lambda oc, ic, ky, kx: oc + 1)            # -> oc       1..128
print("decode: per capture, sort distinct byte values; rank k -> the k-th input "
      "value -> its coordinate. Pad bytes = weight zero-point (constant).")
