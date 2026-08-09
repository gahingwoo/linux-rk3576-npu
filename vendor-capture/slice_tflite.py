#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Cut a contiguous run of operators out of a tflite model into a standalone model.

Why: dwconv.tflite was built in June to isolate the depthwise, and its own
comment claims it uses "conv2d-cal's PROVEN regime", uint8 per-tensor. It does
not. tfl_ops.py shows it is three ops (QUANTIZE, DEPTHWISE_CONV_2D, QUANTIZE)
whose depthwise runs on int8 tensors with PER-AXIS weights and bias. conv2x.tflite
is the same. mobilenet_v1_1.0_224_quant.tflite, the actual target, is uint8
per-tensor everywhere with not one per-axis tensor.

So the two small failing models test a quantization regime nothing has ever
verified, while the model we care about tests a different one. Slicing layers
straight out of MobileNet gives a single depthwise in the regime that matters,
with the real weights and the real scales, and no converter in the loop to
change the regime behind our backs.

Usage: slice_tflite.py <model.tflite> <first_op> <last_op> <out.tflite>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, first, last, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]
    ops = sg.operators[first:last + 1]

    produced = {o for op in ops for o in op.outputs}
    consumed = [i for op in ops for i in op.inputs if i >= 0]

    # Keep every tensor the run touches, in first-seen order, and remap indices.
    keep = []
    for op in ops:
        for t in list(op.inputs) + list(op.outputs):
            if t >= 0 and t not in keep:
                keep.append(t)
    remap = {t: i for i, t in enumerate(keep)}

    new_buffers = [sch.BufferT()]          # index 0 must stay the empty buffer
    new_tensors = []
    for t in keep:
        tensor = sg.tensors[t]
        data = model.buffers[tensor.buffer].data
        if data is None or len(data) == 0:
            tensor.buffer = 0
        else:
            new_buffers.append(model.buffers[tensor.buffer])
            tensor.buffer = len(new_buffers) - 1
        new_tensors.append(tensor)

    # Graph inputs are the tensors the run reads but never writes and that carry
    # no constant data; a weight or bias would otherwise become an input.
    inputs = [remap[t] for t in consumed
              if t not in produced and new_tensors[remap[t]].buffer == 0]
    seen, graph_inputs = set(), []
    for t in inputs:
        if t not in seen:
            seen.add(t)
            graph_inputs.append(t)
    graph_outputs = [remap[o] for o in ops[-1].outputs]

    # Only the opcodes this run uses, renumbered.
    codes, code_map = [], {}
    for op in ops:
        if op.opcodeIndex not in code_map:
            code_map[op.opcodeIndex] = len(codes)
            codes.append(model.operatorCodes[op.opcodeIndex])
        op.opcodeIndex = code_map[op.opcodeIndex]
        op.inputs = [remap[i] if i >= 0 else -1 for i in op.inputs]
        op.outputs = [remap[o] for o in op.outputs]

    sg.tensors = new_tensors
    sg.operators = ops
    sg.inputs = graph_inputs
    sg.outputs = graph_outputs
    model.subgraphs = [sg]
    model.buffers = new_buffers
    model.operatorCodes = codes
    model.signatureDefs = []
    model.metadata = []
    model.metadataBuffer = []

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(out, "wb").write(bytes(b.Output()))
    print(f"wrote {out}: ops {first}..{last}, {len(new_tensors)} tensors, "
          f"inputs={graph_inputs} outputs={graph_outputs}")


main()
