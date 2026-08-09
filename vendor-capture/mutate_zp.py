#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Rewrite the activation zero points of a quantized tflite, leaving geometry,
weights and scales alone.

Why: conv2d-cal is the one configuration that computes correctly on the board,
and the three MobileNet layers sliced out on 2026-08-08 all fail. They differ
from it in several ways at once (input channels 16 vs 32 vs 3, 80x80 vs 112x112
vs 224x224, kernel 5x5 vs 1x1 vs 3x3), but exactly one variable is shared by
every failure and absent from the success: the OUTPUT zero point is 0 on all
three and 128 on conv2d-cal.

Mutating the zero point and nothing else separates that from the geometry. The
CPU reference is recomputed from the same mutated file, so the comparison stays
self-consistent: this asks "does this configuration compute", not "does it match
the original model".

Usage: mutate_zp.py <in.tflite> <out.tflite> [--in-zp N] [--out-zp N]
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst = sys.argv[1], sys.argv[2]
    new_in = new_out = None
    args = sys.argv[3:]
    for i, a in enumerate(args):
        if a == "--in-zp":
            new_in = int(args[i + 1])
        elif a == "--out-zp":
            new_out = int(args[i + 1])

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]

    def set_zp(idx, val, label):
        q = sg.tensors[idx].quantization
        old = list(q.zeroPoint)
        q.zeroPoint = [val] * len(old)
        print(f"  {label} T{idx}: zp {old} -> {list(q.zeroPoint)}")

    if new_in is not None:
        for t in sg.inputs:
            set_zp(t, new_in, "input ")
    if new_out is not None:
        for t in sg.outputs:
            set_zp(t, new_out, "output")

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(b.Output()))
    print(f"wrote {dst}")


main()
