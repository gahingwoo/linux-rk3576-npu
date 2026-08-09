#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Crop a conv's kernel to a smaller odd size, keeping the centre taps.

Why: the 1x1 rewrite fired (weight buffer 256 bytes to 9216, ring taps at
wt_zp - 0x80 = 0xfe) and the resulting 3x3 conv still returns a uniform
out_zp, with a regcmd that matches a vendor .rknn compiled at that exact
geometry. So it is not 1x1 encoding. What the table says now is that 5x5 works
at both strides and at 16 or 128 output channels, while 3x3 and 1x1 do not.

Every failing model so far came from somewhere other than conv2d.tflite, so
"the kernel" and "the model" are still confounded. Cropping conv2d-cal's own
kernel changes one variable off the model that works, the way cal_s1 did for
the stride, which is the mutation that produced the padding result.

Per-tensor quantization makes the crop safe: one scale and zero point cover the
whole weight tensor, so a subset of taps is still validly quantized. SAME
padding keeps the output shape identical for any odd kernel at a given stride,
so nothing else moves.

Usage: mutate_k.py <in.tflite> <out.tflite> <k>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst, k = sys.argv[1], sys.argv[2], int(sys.argv[3])

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]
    op = sg.operators[0]
    w = sg.tensors[op.inputs[1]]

    oc, kh, kw, ic = (int(x) for x in w.shape)
    assert (kh - k) % 2 == 0 and k <= kh, f"cannot crop {kh} to {k}"
    off = (kh - k) // 2

    data = bytes(model.buffers[w.buffer].data)
    assert len(data) == oc * kh * kw * ic

    out = bytearray()
    for o in range(oc):
        for y in range(off, off + k):
            for x in range(off, off + k):
                base = ((o * kh + y) * kw + x) * ic
                out += data[base:base + ic]

    model.buffers[w.buffer].data = list(out)
    w.shape = [oc, k, k, ic]
    print(f"  kernel {kh}x{kw} -> {k}x{k}, centre taps, "
          f"weights {len(data)} -> {len(out)} bytes")

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(b.Output()))
    print(f"wrote {dst}")


main()
