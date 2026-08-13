#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Rebuild every geometry probe used by rounds 105 to 120, from models already in
the tree. .tflite is gitignored, so this file IS the record of them.

There is no tensorflow on this machine and slice_tflite.py needs it, so every
probe here is a byte patch of an existing model, verified by reparsing with the
read-only `tflite` package. Three tricks, and one trap:

  shapes        A graph input or output tensor carries no buffer, so its shape
                vector is free to rewrite. A weight or bias tensor's shape can
                only be made SMALLER.
  buffers       ...and its buffer has to be cut to match. tflite compares the
                two for equality and refuses otherwise: "required_bytes !=
                bytes (576 != 9216), Tensor 1 is invalidly specified in
                schema". Cutting means rewriting the vector's own length
                prefix; the bytes past it become dead space in the file.
  options       stride_w and stride_h are plain int32 fields in the operator's
                options table.
  THE TRAP      flatbuffers omits any field that equals its default. Padding's
                default is SAME, so on a SAME model the field is absent, the
                offset comes back zero, and writing through it lands on the
                table header and corrupts the model. Always check the offset is
                non-zero before writing. That is how one round was lost.

The graph-output probes are different: a subgraph's output list is a length and
one tensor index, so pointing it at any intermediate tensor is a four byte
patch and gives MobileNet itself cut off after that operator, with the real
weights, the real scales and no converter in the loop.

Usage: make_dw_geom.py [outdir]      default rootfs-overlay/opt/npu-test
"""
import os
import struct
import sys

from tflite.DepthwiseConv2DOptions import DepthwiseConv2DOptions
from tflite.Model import Model

SRC = "rootfs-overlay/opt/npu-test"


def _shape_vec(g, idx):
    t = g.Tensors(idx)
    return t._tab.Vector(t._tab.Offset(4))


def _buf_len_pos(m, g, idx):
    buf = m.Buffers(g.Tensors(idx).Buffer())
    off = buf._tab.Offset(4)
    if not off:
        return None
    return buf._tab.Vector(off) - 4


def _set_stride(b, op, stride):
    o = DepthwiseConv2DOptions()
    tab = op.BuiltinOptions()
    o.Init(tab.Bytes, tab.Pos)
    for slot in (6, 8):                      # stride_w, stride_h
        off = o._tab.Offset(slot)
        if not off:                          # absent means it equals 1
            raise SystemExit("stride field absent; cannot patch by bytes")
        struct.pack_into("<i", b, o._tab.Pos + off, stride)


def cut_depthwise(out, name, channels, width, stride=1, base="mn_dw25.tflite"):
    """A standalone depthwise of `channels` at `width`, cut from a bigger one.

    mn_dw25 is 1024 channels at 7x7, so every count and width at or below that
    is reachable by shrinking. Its input and output carry no buffer, so their
    shapes can also GROW.
    """
    b = bytearray(open(os.path.join(SRC, base), "rb").read())
    m = Model.GetRootAsModel(b, 0)
    g = m.Subgraphs(0)
    op = g.Operators(0)
    ins = list(op.InputsAsNumpy())
    o = int(op.Outputs(0))

    ow = width if stride == 1 else (width + stride - 1) // stride
    for k, v in ((1, width), (2, width), (3, channels)):
        struct.pack_into("<i", b, _shape_vec(g, ins[0]) + 4 * k, v)
    struct.pack_into("<i", b, _shape_vec(g, ins[1]) + 4 * 3, channels)
    struct.pack_into("<i", b, _shape_vec(g, ins[2]) + 4 * 0, channels)
    for k, v in ((1, ow), (2, ow), (3, channels)):
        struct.pack_into("<i", b, _shape_vec(g, o) + 4 * k, v)
    for idx, nbytes in ((ins[1], 9 * channels), (ins[2], 4 * channels)):
        pos = _buf_len_pos(m, g, idx)
        struct.pack_into("<I", b, pos, nbytes)
    if stride != 1:
        _set_stride(b, op, stride)

    path = os.path.join(out, name + ".tflite")
    open(path, "wb").write(bytes(b))
    return verify_dw(path, channels, width, ow, stride)


def cut_pointwise(out, name, ic, oc, width, base="mn_pw24.tflite"):
    """A standalone 1x1 convolution of ic to oc at `width`, cut from a bigger one.

    mn_pw24 is 512 to 1024 at 7x7, so every pair at or below that is reachable
    by shrinking. Same rules as cut_depthwise: the graph input and output carry
    no buffer so their shapes are free, and the weight and bias buffers have to
    be cut to match exactly.

    Added for round 126. Only one standalone pointwise had ever been run here,
    mn_pw2 at 32 to 64, and MobileNet's operator 4 is 64 to 128.
    """
    b = bytearray(open(os.path.join(SRC, base), "rb").read())
    m = Model.GetRootAsModel(b, 0)
    g = m.Subgraphs(0)
    op = g.Operators(0)
    ins = list(op.InputsAsNumpy())
    o = int(op.Outputs(0))

    for k, v in ((1, width), (2, width), (3, ic)):
        struct.pack_into("<i", b, _shape_vec(g, ins[0]) + 4 * k, v)
    struct.pack_into("<i", b, _shape_vec(g, ins[1]) + 4 * 0, oc)
    struct.pack_into("<i", b, _shape_vec(g, ins[1]) + 4 * 3, ic)
    struct.pack_into("<i", b, _shape_vec(g, ins[2]) + 4 * 0, oc)
    for k, v in ((1, width), (2, width), (3, oc)):
        struct.pack_into("<i", b, _shape_vec(g, o) + 4 * k, v)
    for idx, nbytes in ((ins[1], oc * ic), (ins[2], 4 * oc)):
        struct.pack_into("<I", b, _buf_len_pos(m, g, idx), nbytes)

    path = os.path.join(out, name + ".tflite")
    open(path, "wb").write(bytes(b))

    m2 = Model.GetRootAsModel(bytearray(open(path, "rb").read()), 0)
    g2 = m2.Subgraphs(0)
    op2 = g2.Operators(0)
    i2 = list(op2.InputsAsNumpy())
    assert list(g2.Tensors(i2[1]).ShapeAsNumpy()) == [oc, 1, 1, ic], name
    assert m2.Buffers(g2.Tensors(i2[1]).Buffer()).DataLength() == oc * ic, name
    at = (ic + 15) // 16
    last = at % 8
    eps = (at // 8) * width + (width if last == 3 else -(-last * width // 8))
    return ("%-11s %4d->%-4d %3dwide  %3d entries/row  %5d entries  %s"
            % (name, ic, oc, width, eps, eps * width,
               "over the layer budget" if eps * width > 5120 else "fits"))


def restride(out, name, src, op_index, stride, out_size):
    """The same model with one operator's stride changed."""
    b = bytearray(open(os.path.join(SRC, src), "rb").read())
    g = Model.GetRootAsModel(b, 0).Subgraphs(0)
    op = g.Operators(op_index)
    _set_stride(b, op, stride)
    vec = _shape_vec(g, int(op.Outputs(0)))
    struct.pack_into("<i", b, vec + 4 * 1, out_size)
    struct.pack_into("<i", b, vec + 4 * 2, out_size)
    path = os.path.join(out, name + ".tflite")
    open(path, "wb").write(bytes(b))

    g2 = Model.GetRootAsModel(bytearray(open(path, "rb").read()), 0).Subgraphs(0)
    op2 = g2.Operators(op_index)
    o2 = DepthwiseConv2DOptions()
    t2 = op2.BuiltinOptions()
    o2.Init(t2.Bytes, t2.Pos)
    shape = list(g2.Tensors(int(op2.Outputs(0))).ShapeAsNumpy())
    assert o2.StrideW() == stride and o2.StrideH() == stride, name
    assert shape[1] == out_size, name
    return "%-11s stride %d  out %s" % (name, stride, shape)


def layer_probe(out, name, tensor, src="mobilenet_v1_1.0_224_quant.tflite"):
    """MobileNet with its graph output moved to an intermediate tensor."""
    raw = open(os.path.join(SRC, src), "rb").read()
    g = Model.GetRootAsModel(bytearray(raw), 0).Subgraphs(0)
    cur = int(g.Outputs(0))
    pat = struct.pack("<ii", 1, cur)
    hits = [i for i in range(len(raw) - 8) if raw[i:i + 8] == pat]
    good = None
    for h in hits:                    # the same pattern occurs more than once
        t = bytearray(raw)
        struct.pack_into("<i", t, h + 4, tensor)
        try:
            if int(Model.GetRootAsModel(t, 0).Subgraphs(0).Outputs(0)) == tensor:
                good = t
                break
        except Exception:
            pass
    if good is None:
        raise SystemExit("could not find the subgraph output field")
    path = os.path.join(out, name + ".tflite")
    open(path, "wb").write(bytes(good))
    g2 = Model.GetRootAsModel(bytearray(open(path, "rb").read()), 0).Subgraphs(0)
    return "%-11s -> tensor %3d shape %s" % (
        name, tensor, list(g2.Tensors(int(g2.Outputs(0))).ShapeAsNumpy()))


def verify_dw(path, channels, width, ow, stride):
    m = Model.GetRootAsModel(bytearray(open(path, "rb").read()), 0)
    g = m.Subgraphs(0)
    op = g.Operators(0)
    ins = list(op.InputsAsNumpy())
    ish = list(g.Tensors(ins[0]).ShapeAsNumpy())
    wl = m.Buffers(g.Tensors(ins[1]).Buffer()).DataLength()
    assert ish[1] == width and ish[3] == channels, path
    assert wl == 9 * channels, (path, wl)
    at = (channels + 15) // 16
    last = at % 8
    eps = (at // 8) * width + (width if last == 3 else -(-last * width // 8))
    return ("%-11s %4dch %3dwide s%d  %3d entries/row  %5d entries  %s"
            % (os.path.basename(path)[:-7], channels, width, stride, eps,
               eps * width,
               "over budget" if eps * width > 2560 else "fits in 2560"))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else SRC
    os.makedirs(out, exist_ok=True)

    # The channel bisection at 112 wide, rounds 113 and 114.
    for c in (16, 32, 40, 48, 56, 64, 96, 128):
        print(cut_depthwise(out, "dw%d" % c, c, 112))
    print(cut_depthwise(out, "dw64_s2", 64, 112, stride=2))

    # The width ladder at a fixed channel count, rounds 115 to 120.
    # 71 and 72 are the odd/even pair that both fit ONE window, so odd width
    # can be asked without a split in the way, rounds 120 to 121.
    for c, w in ((64, 48), (64, 64), (64, 70), (64, 72), (64, 80), (64, 96),
                 (64, 110), (32, 96), (32, 109), (32, 110), (32, 111),
                 (16, 96), (128, 44), (32, 71), (32, 72),
                 # rounds 122: the even bisect between 96, which passes, and
                 # 110, which does not, and two odd widths where surf is exact
                 (64, 98), (64, 100), (64, 104), (64, 108),
                 (64, 71), (32, 31),
                 # round 123: the WHOLE layer's staged CBUF, tested at three
                 # channel counts. Per window is 5 banks; the total looks like 10
                 (32, 136), (32, 152), (64, 102), (128, 64), (128, 80)):
        print(cut_depthwise(out, "dw%dw%d" % (c, w), c, w))

    # Stride patched onto models that are correct at stride 1, rounds 106..110.
    print(restride(out, "dw1_s2", "mn_dw1.tflite", 0, 2, 56))
    print(restride(out, "dw25_s2", "mn_dw25.tflite", 0, 2, 4))
    print(restride(out, "c0dw1_s2", "mn_conv0dw1.tflite", 1, 2, 56))

    # Standalone pointwise, round 126. op4 of MobileNet is 64 to 128 at 56 wide
    # and only 32 to 64 had ever been run on its own.
    for ic, oc, w in ((64, 128, 56), (32, 64, 56), (64, 64, 56), (128, 128, 56),
                      (64, 128, 28), (128, 256, 28)):
        print(cut_pointwise(out, "pw%dx%dw%d" % (ic, oc, w), ic, oc, w))

    # MobileNet cut off after each operator, rounds 103 and 104.
    for op, tensor in ((0, 7), (1, 33), (2, 37), (3, 39), (4, 43), (5, 45),
                       (6, 49), (7, 51), (8, 55), (12, 67), (18, 85),
                       (24, 25), (26, 31)):
        print(layer_probe(out, "mn_L%02d" % op, tensor))


if __name__ == "__main__":
    main()
