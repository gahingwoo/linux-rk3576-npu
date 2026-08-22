#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Igor Paunovic
# mk1x1.py - build a quantised TFLite model: CONV_2D 1x1, 64 input channels,
# oc output channels. Written to probe how the rocket encoder behaves as the
# output channel count varies.
#
# The flatbuffer is built BY HAND, because the tflite pip package is a reader
# only. Vtable slots are taken from the installed package's accessors
# (slot = (Offset - 4) / 2) and the enums come straight from the package, so
# nothing here is guessed.
#
# Design choices, each one there to remove a way of fooling ourselves:
#
#  - zp_out = 0. Then the hardware's "ReLU at the output zero point" is the
#    same thing as uint8 saturation, which is what the CPU reference does too.
#    A clamp cannot manufacture a fake NPU-vs-CPU difference.
#
#  - fused RELU6, the same activation MobileNet uses, so the delegate is
#    certain to take the path. With s_out <= 6/255 the ceiling is >= 255, i.e.
#    RELU6 is a no-op across the whole uint8 range.
#
#  - weights 128 +/- 16 and bias > 0 are chosen so that NO channel comes out
#    constant, and so that saturation stays low. A constant reference channel
#    would "match" trivially and prove nothing. The generator CHECKS this with
#    the CPU interpreter after writing each model and refuses to emit one that
#    fails.
#
# Usage:  python3 mk1x1.py 56 88 120
#         OUTDIR=/some/where python3 mk1x1.py 20 60
#
# Requires: numpy, flatbuffers, tflite (the schema package), tflite_runtime.
import os
import sys

import numpy as np
import flatbuffers
from tflite.TensorType import TensorType
from tflite.BuiltinOperator import BuiltinOperator
from tflite.BuiltinOptions import BuiltinOptions
from tflite.Padding import Padding
from tflite.ActivationFunctionType import ActivationFunctionType

H = W = 8
IC = 64
S_IN, ZP_IN = 1.0 / 128, 128
S_W, ZP_W = 0.02, 128
S_OUT, ZP_OUT = 0.0235, 0     # 6/0.0235 = 255.3, so the RELU6 ceiling is
                              # above the top of the uint8 range
S_BIAS = S_IN * S_W
OUTDIR = os.environ.get("OUTDIR", ".")


def tbl(b, slots):
    """slots: list of (slot, kind, value); kind in 'off','i8','u8','i32','u32'"""
    b.StartObject(1 + max(s for s, _, _ in slots) if slots else 1)
    for slot, kind, val in slots:
        if kind == "off":
            b.PrependUOffsetTRelativeSlot(slot, val, 0)
        elif kind == "i8":
            b.PrependInt8Slot(slot, val, 0)
        elif kind == "u8":
            b.PrependUint8Slot(slot, val, 0)
        elif kind == "i32":
            b.PrependInt32Slot(slot, val, 0)
        elif kind == "u32":
            b.PrependUint32Slot(slot, val, 0)
    return b.EndObject()


def tblvec(b, offs):
    b.StartVector(4, len(offs), 4)
    for o in reversed(offs):
        b.PrependUOffsetTRelative(o)
    return b.EndVector()


def quant(b, scales, zps):
    sv = b.CreateNumpyVector(np.asarray(scales, dtype=np.float32))
    zv = b.CreateNumpyVector(np.asarray(zps, dtype=np.int64))
    return tbl(b, [(2, "off", sv), (3, "off", zv)])


def tensor(b, shape, ttype, buf, name, q):
    shv = b.CreateNumpyVector(np.asarray(shape, dtype=np.int32))
    nm = b.CreateString(name)
    return tbl(b, [(0, "off", shv), (1, "i8", ttype), (2, "u32", buf),
                   (3, "off", nm), (4, "off", q)])


def build(oc):
    rng = np.random.default_rng(1234 + oc)
    wq = rng.integers(ZP_W - 16, ZP_W + 17, size=(oc, 1, 1, IC)).astype(np.uint8)
    bias = rng.integers(1300, 22000, size=(oc,)).astype(np.int32)

    b = flatbuffers.Builder(1024 * 64)

    wdata = b.CreateByteVector(wq.tobytes())
    bdata = b.CreateByteVector(bias.tobytes())       # int32, little endian
    buf_empty1 = tbl(b, [])                          # buffers[0] must be empty
    buf_w = tbl(b, [(0, "off", wdata)])
    buf_b = tbl(b, [(0, "off", bdata)])
    # Order in the file does not matter; order IN THE VECTOR does.
    buffers = tblvec(b, [buf_empty1, buf_w, buf_b])

    q_in = quant(b, [S_IN], [ZP_IN])
    q_w = quant(b, [S_W], [ZP_W])
    q_b = quant(b, [S_BIAS], [0])
    q_out = quant(b, [S_OUT], [ZP_OUT])

    t_in = tensor(b, (1, H, W, IC), TensorType.UINT8, 0, "input", q_in)
    t_w = tensor(b, (oc, 1, 1, IC), TensorType.UINT8, 1, "weights", q_w)
    t_b = tensor(b, (oc,), TensorType.INT32, 2, "bias", q_b)
    t_out = tensor(b, (1, H, W, oc), TensorType.UINT8, 0, "output", q_out)
    tensors = tblvec(b, [t_in, t_w, t_b, t_out])

    conv_opts = tbl(b, [(0, "i8", Padding.VALID), (1, "i32", 1), (2, "i32", 1),
                        (3, "i8", ActivationFunctionType.RELU6)])
    op_in = b.CreateNumpyVector(np.asarray([0, 1, 2], dtype=np.int32))
    op_out = b.CreateNumpyVector(np.asarray([3], dtype=np.int32))
    op = tbl(b, [(1, "off", op_in), (2, "off", op_out),
                 (3, "u8", BuiltinOptions.Conv2DOptions), (4, "off", conv_opts)])
    ops = tblvec(b, [op])

    sg_in = b.CreateNumpyVector(np.asarray([0], dtype=np.int32))
    sg_out = b.CreateNumpyVector(np.asarray([3], dtype=np.int32))
    sg_name = b.CreateString(f"conv1x1_oc{oc}")
    sg = tbl(b, [(0, "off", tensors), (1, "off", sg_in), (2, "off", sg_out),
                 (3, "off", ops), (4, "off", sg_name)])
    sgs = tblvec(b, [sg])

    opcode = tbl(b, [(0, "i8", BuiltinOperator.CONV_2D),
                     (3, "i32", BuiltinOperator.CONV_2D)])
    opcodes = tblvec(b, [opcode])

    desc = b.CreateString(f"1x1 conv {IC}->{oc} uint8, output-channel probe")
    model = tbl(b, [(0, "u32", 3), (1, "off", opcodes), (2, "off", sgs),
                    (3, "off", desc), (4, "off", buffers)])
    b.Finish(model, file_identifier=b"TFL3")
    return bytes(b.Output())


def verify_cpu(path, oc):
    """Use the CPU interpreter both as a format validator and as a guard: no
    channel may be constant, and saturation must stay low. Same input pattern
    as the scorer uses."""
    import tflite_runtime.interpreter as tfl
    it = tfl.Interpreter(model_path=path)
    it.allocate_tensors()
    ni, no = it.get_input_details()[0], it.get_output_details()[0]
    n = int(np.prod(ni["shape"]))
    data = ((np.arange(n) * 7) % 251).astype(np.uint8)
    it.set_tensor(ni["index"], data.reshape(ni["shape"]))
    it.invoke()
    out = it.get_tensor(no["index"])[0].astype(int)       # (H, W, oc)
    per_ch = out.reshape(-1, oc)
    const = int(np.sum(per_ch.max(0) == per_ch.min(0)))
    sat = float(np.mean((per_ch == 0) | (per_ch == 255)))
    print(f"  CPU check: out {out.shape} min={out.min()} max={out.max()} "
          f"constant channels={const} saturation={sat:.1%}")
    if const:
        raise SystemExit(f"REJECTED: {const} constant channels - "
                         f"this model cannot discriminate")
    if sat > 0.30:
        raise SystemExit(f"REJECTED: saturation {sat:.1%} > 30%")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        oc = int(arg)
        path = os.path.join(OUTDIR, f"conv1x1-oc{oc:03d}.tflite")
        open(path, "wb").write(build(oc))
        print(f"oc={oc}: {path} ({len(open(path,'rb').read())} B)")
        verify_cpu(path, oc)
