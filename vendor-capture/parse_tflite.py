#!/usr/bin/env python3
"""
Minimal TFLite flatbuffer reader (no tensorflow / tflite_runtime needed): pull
the conv op's shape + stride/pad + per-tensor quant, and the raw weight/bias
bytes. Used to build a matching ONNX so the vendor .rknn runs the IDENTICAL conv.

Navigates the schema by vtable field index:
  Model:    subgraphs=2, buffers=4, operator_codes=1
  SubGraph: tensors=0, inputs=1, outputs=2, operators=3
  Tensor:   shape=0, type=1, buffer=2, name=3, quantization=4
  Quant:    scale=1, zero_point=2
  Operator: opcode_index=0, inputs=1, outputs=2, builtin_options=4 (+type=3)
  Conv2DOptions: padding=0, stride_w=1, stride_h=2
  Buffer:   data=0
"""
import sys
import struct
import flatbuffers
from flatbuffers import table, encode
from flatbuffers.number_types import (UOffsetTFlags, SOffsetTFlags,
                                       Uint32Flags, Int32Flags, Uint8Flags,
                                       Int8Flags, Float32Flags)

TYPES = {0: "f32", 1: "f16", 2: "i32", 3: "u8", 4: "i64", 5: "str",
         6: "bool", 7: "i16", 9: "i8", 17: "i4"}


def root_table(buf):
    off = encode.Get(UOffsetTFlags.packer_type, buf, 0)
    return table.Table(buf, off)


def sub_table(t, field):
    o = t.Offset(4 + field * 2)
    if o == 0:
        return None
    return table.Table(t.Bytes, t.Indirect(o + t.Pos))


def vec_len(t, field):
    o = t.Offset(4 + field * 2)
    return t.VectorLen(o) if o else 0


def vec_table(t, field, i):
    o = t.Offset(4 + field * 2)
    start = t.Vector(o)
    return table.Table(t.Bytes, t.Indirect(start + i * 4))


def vec_i32(t, field):
    o = t.Offset(4 + field * 2)
    if o == 0:
        return []
    n = t.VectorLen(o)
    start = t.Vector(o)
    return [t.Get(Int32Flags, start + i * 4) for i in range(n)]


def vec_f32(t, field):
    o = t.Offset(4 + field * 2)
    if o == 0:
        return []
    n = t.VectorLen(o)
    start = t.Vector(o)
    return [t.Get(Float32Flags, start + i * 4) for i in range(n)]


def scalar(t, field, flag, default=0):
    o = t.Offset(4 + field * 2)
    return t.Get(flag, o + t.Pos) if o else default


def buffer_bytes(model, idx):
    bufs = model  # model table
    o = bufs.Offset(4 + 4 * 2)  # buffers field=4
    start = bufs.Vector(o)
    bt = table.Table(bufs.Bytes, bufs.Indirect(start + idx * 4))
    do = bt.Offset(4 + 0 * 2)  # data=0
    if do == 0:
        return b""
    n = bt.VectorLen(do)
    ds = bt.Vector(do)
    return bytes(bt.Bytes[ds:ds + n])


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "conv2d.tflite"
    buf = bytearray(open(path, "rb").read())
    model = root_table(buf)

    sg = vec_table(model, 2, 0)  # subgraphs[0]
    ntensors = vec_len(sg, 0)
    inputs = vec_i32(sg, 1)
    outputs = vec_i32(sg, 2)

    print(f"== {path} ==")
    print(f"subgraph: {ntensors} tensors, inputs={inputs} outputs={outputs}")

    tensors = []
    for i in range(ntensors):
        tt = vec_table(sg, 0, i)
        shape = vec_i32(tt, 0)
        typ = scalar(tt, 1, Uint8Flags, 0)
        bufidx = scalar(tt, 2, Uint32Flags, 0)
        q = sub_table(tt, 4)
        scl = vec_f32(q, 1) if q else []
        zp = vec_i32(q, 2) if q else []
        tensors.append(dict(shape=shape, type=TYPES.get(typ, typ),
                            buf=bufidx, scale=scl, zp=zp))
        print(f"  T{i}: shape={shape} type={TYPES.get(typ, typ)} buf={bufidx} "
              f"scale={scl[:1]}{'..' if len(scl) > 1 else ''}({len(scl)}) "
              f"zp={zp[:1]}{'..' if len(zp) > 1 else ''}")

    # operators
    for oi in range(vec_len(sg, 3)):
        op = vec_table(sg, 3, oi)
        op_inputs = vec_i32(op, 1)
        op_outputs = vec_i32(op, 2)
        bo = sub_table(op, 4)  # builtin_options (Conv2DOptions)
        pad = scalar(bo, 0, Uint8Flags, 0) if bo else None
        sw = scalar(bo, 1, Int32Flags, 0) if bo else None
        sh = scalar(bo, 2, Int32Flags, 0) if bo else None
        print(f"  OP{oi}: in={op_inputs} out={op_outputs} "
              f"pad={'SAME' if pad == 0 else 'VALID' if pad == 1 else pad} "
              f"stride=({sw},{sh})")

    # dump raw weight + bias bytes for the conv (input[1]=weights, input[2]=bias)
    if vec_len(sg, 3) >= 1:
        op = vec_table(sg, 3, 0)
        oin = vec_i32(op, 1)
        if len(oin) >= 2:
            wt = tensors[oin[1]]
            wb = buffer_bytes(model, wt["buf"])
            open("conv2d_weights.i8", "wb").write(wb)
            print(f"  -> weights tensor T{oin[1]} shape={wt['shape']} "
                  f"{len(wb)} bytes -> conv2d_weights.i8")
        if len(oin) >= 3:
            bt = tensors[oin[2]]
            bb = buffer_bytes(model, bt["buf"])
            open("conv2d_bias.i32", "wb").write(bb)
            print(f"  -> bias tensor T{oin[2]} shape={bt['shape']} "
                  f"{len(bb)} bytes -> conv2d_bias.i32")


if __name__ == "__main__":
    main()
