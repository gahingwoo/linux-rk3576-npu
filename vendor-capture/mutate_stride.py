#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Change a conv's stride and resize its output tensor to match, leaving weights,
scales and zero points alone.

Why: round 2 refuted both surviving hypotheses. The output zero point is not it
(conv2d-cal still computes with out_zp forced to 0) and the task split is not it
(mn_pw24 is one task and still fails). What is left in the table is that
conv2d-cal is 5x5 stride 2 and every failing model is stride 1, and that
conv2d-cal is the only convolution geometry this driver has ever computed
correctly at all.

Changing only the stride separates it from kernel size and from everything else
in the model. SAME padding means the output becomes ceil(in/stride), which this
resizes; the buffer for an activation tensor is empty at rest, so only dims move.
The CPU reference recomputes from the mutated file.

Usage: mutate_stride.py <in.tflite> <out.tflite> <stride>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst, stride = sys.argv[1], sys.argv[2], int(sys.argv[3])

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]

    for op in sg.operators:
        opt = op.builtinOptions
        if opt is None or not hasattr(opt, "strideW"):
            continue
        in_t = sg.tensors[op.inputs[0]]
        out_t = sg.tensors[op.outputs[0]]
        old = (opt.strideW, opt.strideH)
        opt.strideW = opt.strideH = stride
        # SAME padding: out = ceil(in / stride). padding enum 0 = SAME.
        h, w = in_t.shape[1], in_t.shape[2]
        new_shape = list(out_t.shape)
        new_shape[1] = -(-h // stride)
        new_shape[2] = -(-w // stride)
        print(f"  stride {old} -> ({stride}, {stride}), "
              f"output {list(out_t.shape)} -> {new_shape}")
        out_t.shape = new_shape

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(b.Output()))
    print(f"wrote {dst}")


main()
