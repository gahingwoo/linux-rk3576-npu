#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
An exact-arithmetic reference for a single operator model.

WHY THIS EXISTS. Every accuracy number in this project was scored against the
tflite interpreter, and round 257 showed that on three of four models the
interpreter is the one that is wrong. Its requant is a
SaturatingRoundingDoublingHighMul followed by a RoundingDivideByPOT, which
rounds a half away from zero, and computed offline against exact arithmetic it
reads HIGH on 14.41 percent of mn_dw1's pixels, 0.86 of mn_pw2's and 0.18 of
mn_pw24's. The board measured the hardware differing from the interpreter on
14.38, 0.78 and 0.19 percent of the same pixels, every one of them the other
way. The hardware is the accurate one.

So a knob that improves agreement with the interpreter makes the driver less
accurate, and ROCKET_ABIAS=1 is exactly such a knob: it took mn_dw1 from 85.62
to 98.88 percent agreement by adopting the interpreter's error.

This computes what the operator actually means, in integers, and rounds once at
the end. Supported: a single CONV_2D or DEPTHWISE_CONV_2D over uint8 with SAME
or VALID padding. Anything else returns None and the caller keeps its old
reference.
"""
import numpy as np

try:
    from tflite.Model import Model
    from tflite.BuiltinOperator import BuiltinOperator as BO
    from tflite.Padding import Padding
    from tflite.Conv2DOptions import Conv2DOptions
    from tflite.DepthwiseConv2DOptions import DepthwiseConv2DOptions
except Exception:
    Model = None


def exact_reference(path, x_uint8):
    """Return the exact uint8 output, or None if this model is not covered."""
    if Model is None:
        return None
    m = Model.GetRootAsModel(bytearray(open(path, 'rb').read()), 0)
    sg = m.Subgraphs(0)
    if sg.OperatorsLength() != 1:
        return None
    op = sg.Operators(0)
    code = m.OperatorCodes(op.OpcodeIndex()).BuiltinCode()
    depthwise = code == BO.DEPTHWISE_CONV_2D
    if code != BO.CONV_2D and not depthwise:
        return None
    if op.InputsLength() < 3:
        return None

    it = sg.Tensors(op.Inputs(0))
    wt = sg.Tensors(op.Inputs(1))
    bt = sg.Tensors(op.Inputs(2))
    ot = sg.Tensors(op.Outputs(0))
    ish = [it.Shape(i) for i in range(it.ShapeLength())]
    wsh = [wt.Shape(i) for i in range(wt.ShapeLength())]
    osh = [ot.Shape(i) for i in range(ot.ShapeLength())]
    if len(ish) != 4 or len(wsh) != 4 or len(osh) != 4:
        return None

    o = DepthwiseConv2DOptions() if depthwise else Conv2DOptions()
    o.Init(op.BuiltinOptions().Bytes, op.BuiltinOptions().Pos)
    sy, sx = o.StrideH(), o.StrideW()
    same = o.Padding() == Padding.SAME
    if depthwise and o.DepthMultiplier() != 1:
        return None

    W = np.frombuffer(m.Buffers(wt.Buffer()).DataAsNumpy().tobytes(),
                      dtype=np.uint8).reshape(wsh).astype(np.int64)
    B = np.frombuffer(m.Buffers(bt.Buffer()).DataAsNumpy().tobytes(),
                      dtype=np.int32).astype(np.int64)

    iq, wq, oq = it.Quantization(), wt.Quantization(), ot.Quantization()
    in_zp = iq.ZeroPoint(0)
    in_sc = iq.Scale(0)
    out_zp = oq.ZeroPoint(0)
    out_sc = oq.Scale(0)
    w_zp = np.array([wq.ZeroPoint(i) for i in range(wq.ZeroPointLength())],
                    dtype=np.int64)
    w_sc = np.array([wq.Scale(i) for i in range(wq.ScaleLength())],
                    dtype=np.float64)

    H, Wd, IC = ish[1], ish[2], ish[3]
    OH, OW, OC = osh[1], osh[2], osh[3]
    kh, kw = wsh[1], wsh[2]

    X = x_uint8.astype(np.int64).reshape(1, H, Wd, IC) - in_zp
    if same:
        py = max((OH - 1) * sy + kh - H, 0)
        px = max((OW - 1) * sx + kw - Wd, 0)
    else:
        py = px = 0
    Xp = np.zeros((1, H + py, Wd + px, IC), dtype=np.int64)
    Xp[:, py // 2:py // 2 + H, px // 2:px // 2 + Wd, :] = X

    acc = np.zeros((1, OH, OW, OC), dtype=np.int64)
    if depthwise:
        Wc = W[0] - (w_zp if w_zp.size == OC else w_zp[0])
        for ky in range(kh):
            for kx in range(kw):
                acc += Xp[:, ky:ky + OH * sy:sy, kx:kx + OW * sx:sx, :] * Wc[ky, kx, :]
    else:
        Wc = W - (w_zp.reshape(-1, 1, 1, 1) if w_zp.size == OC else w_zp[0])
        for ky in range(kh):
            for kx in range(kw):
                patch = Xp[:, ky:ky + OH * sy:sy, kx:kx + OW * sx:sx, :]
                acc += np.tensordot(patch, Wc[:, ky, kx, :], axes=([3], [1]))
    acc += B

    mult = in_sc * (w_sc if w_sc.size == OC else np.full(OC, w_sc[0])) / out_sc
    #
    # One rounding, at the end, on the real value. Nothing here is a fixed
    # point approximation, which is the whole point of calling it exact.
    #
    y = np.floor(acc * mult + out_zp + 0.5)
    return np.clip(y, 0, 255).astype(np.int64)[0]
