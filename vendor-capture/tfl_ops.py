#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What ops and what quantization does a tflite file actually contain?

parse_tflite.py reports shapes but prints the quantization fields as raw float
bits, which reads as nonsense. This prints the resolved builtin op codes and,
per tensor, the dtype, how many scales it carries (>1 means per-axis) and the
zero points. That is the difference between "uint8 per-tensor", the regime this
project proved correct, and "int8 per-channel", which is a different datapath.

Usage: tfl_ops.py <model.tflite>
"""
import sys

from flatbuffers import table, encode
from flatbuffers.number_types import (UOffsetTFlags, Int32Flags, Int8Flags,
                                      Float32Flags, Int64Flags)

TYPES = {0: "f32", 1: "f16", 2: "i32", 3: "u8", 4: "i64", 5: "str",
         6: "bool", 7: "i16", 9: "i8", 17: "i4"}

# tflite BuiltinOperator, only the ones this project emits
OPS = {0: "ADD", 1: "AVERAGE_POOL_2D", 2: "CONCATENATION", 3: "CONV_2D",
       4: "DEPTHWISE_CONV_2D", 9: "FULLY_CONNECTED", 17: "MAX_POOL_2D",
       22: "RESHAPE", 25: "SOFTMAX", 34: "PAD", 40: "MEAN", 114: "QUANTIZE",
       6: "DEQUANTIZE", 32: "CUSTOM"}


def root_table(buf):
    return table.Table(buf, encode.Get(UOffsetTFlags.packer_type, buf, 0))


def sub_table(t, field):
    o = t.Offset(4 + field * 2)
    return table.Table(t.Bytes, t.Indirect(o + t.Pos)) if o else None


def vec_len(t, field):
    o = t.Offset(4 + field * 2)
    return t.VectorLen(o) if o else 0


def vec_table(t, field, i):
    o = t.Offset(4 + field * 2)
    return table.Table(t.Bytes, t.Indirect(t.Vector(o) + i * 4))


def vec_of(t, field, flag, size):
    o = t.Offset(4 + field * 2)
    if o == 0:
        return []
    n, start = t.VectorLen(o), t.Vector(o)
    return [t.Get(flag, start + i * size) for i in range(n)]


def scalar(t, field, flag, default=0):
    o = t.Offset(4 + field * 2)
    return t.Get(flag, o + t.Pos) if o else default


def main():
    buf = bytearray(open(sys.argv[1], "rb").read())
    model = root_table(buf)

    # operator_codes=1: builtin_code=3 (i32) supersedes deprecated_builtin_code=0
    codes = []
    for i in range(vec_len(model, 1)):
        oc = vec_table(model, 1, i)
        big = scalar(oc, 3, Int32Flags, 0)
        small = scalar(oc, 0, Int8Flags, 0)
        codes.append(big if big else small)

    sg = vec_table(model, 2, 0)
    print(f"== {sys.argv[1]} ==")
    print(f"  inputs={vec_of(sg, 1, Int32Flags, 4)} outputs={vec_of(sg, 2, Int32Flags, 4)}")

    print("  tensors:")
    for i in range(vec_len(sg, 0)):
        t = vec_table(sg, 0, i)
        shape = vec_of(t, 0, Int32Flags, 4)
        typ = TYPES.get(scalar(t, 1, Int8Flags, 0), "?")
        q = sub_table(t, 4)
        # Quantization: min=0 max=1 scale=2 zero_point=3 (parse_tflite.py's
        # header comment says 1 and 2, which reads the min/max vectors instead)
        sc = vec_of(q, 2, Float32Flags, 4) if q else []
        zp = vec_of(q, 3, Int64Flags, 8) if q else []
        axis = "per-axis" if len(sc) > 1 else "per-tensor" if sc else "none"
        s0 = f"{sc[0]:.6g}" if sc else "-"
        print(f"    T{i}: {typ:4s} {str(shape):24s} {axis:10s} nscale={len(sc):3d} "
              f"scale0={s0} zp={zp[:4]}")

    print("  ops:")
    for i in range(vec_len(sg, 3)):
        op = vec_table(sg, 3, i)
        ci = scalar(op, 0, Int32Flags, 0)
        code = codes[ci] if ci < len(codes) else -1
        ins = vec_of(op, 1, Int32Flags, 4)
        outs = vec_of(op, 2, Int32Flags, 4)
        print(f"    op{i}: {OPS.get(code, str(code)):20s} in={ins} out={outs}")


main()
