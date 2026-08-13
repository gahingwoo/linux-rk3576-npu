#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What does CORRECT hardware score against tflite, layer by layer, on MobileNet?

Rounds 99 to 101 settled that the pervasive one sided off-by-one is tflite's own
double rounding and not the hardware: tflite requantises with
SaturatingRoundingDoublingHighMul followed by RoundingDivideByPOT, whose
intermediate lands on exactly one half for a large share of pixels and rounds up
every time, while the hardware rounds a shift half up once. On a single layer
that is a handful of counts. Chained, it compounds, and by operator 8 a
perfectly correct accelerator would score 34 of 256 channels against the CPU.

So a channel count off the board means nothing on its own past the first layer
or two. This runs the whole graph twice from the model file, once with tflite's
arithmetic and once with the hardware's, and prints what the board should read
if nothing at all were wrong. That number is the decision rule for every
remaining round, and the table it prints for operators 0, 1, 2, 4, 6 and 8 is
the one FINDINGS carries from round 104.

perch.py's input, so the two are directly comparable.

Usage: chainmodel.py [model.tflite] [--upto N]
"""
import sys

import numpy as np
from tflite.BuiltinOperator import BuiltinOperator
from tflite.Model import Model
from tflite.Padding import Padding
from tflite.ActivationFunctionType import ActivationFunctionType
from tflite.Conv2DOptions import Conv2DOptions
from tflite.DepthwiseConv2DOptions import DepthwiseConv2DOptions
from tflite.Pool2DOptions import Pool2DOptions

SRC = "rootfs-overlay/opt/npu-test/mobilenet_v1_1.0_224_quant.tflite"


def quantize_multiplier(m):
    """tflite's decomposition of a real multiplier into (int32, shift)."""
    if m == 0.0:
        return 0, 0
    frac, exp = np.frexp(m)                    # m = frac * 2**exp, frac in [.5,1)
    q = int(round(frac * (1 << 31)))
    if q == (1 << 31):
        q //= 2
        exp += 1
    return q, exp


def srdhm(a, b):
    """SaturatingRoundingDoublingHighMul, on int32 lanes held in int64."""
    ab = a.astype(np.int64) * np.int64(b)
    nudge = np.where(ab >= 0, 1 << 30, 1 - (1 << 30))
    out = (ab + nudge) >> 31
    return np.clip(out, -(1 << 31), (1 << 31) - 1)


def rdbypot(x, exp):
    """RoundingDivideByPOT, round half away from zero."""
    if exp == 0:
        return x
    mask = (1 << exp) - 1
    rem = x & mask
    thr = (mask >> 1) + (x < 0).astype(np.int64)
    return (x >> exp) + (rem > thr).astype(np.int64)


def requant_tflite(acc, m):
    q, exp = quantize_multiplier(m)
    shift = -exp                                # m < 1 so exp <= 0
    return rdbypot(srdhm(acc, q), shift)


def requant_hw(acc, m):
    """One shift, rounded half up, which is what the hardware does."""
    return np.floor(acc.astype(np.float64) * m + 0.5).astype(np.int64)


def pad_for(ih, iw, kh, kw, sh, sw, padding):
    if padding != Padding.SAME:
        return 0, 0, 0, 0
    oh, ow = -(-ih // sh), -(-iw // sw)
    ph = max((oh - 1) * sh + kh - ih, 0)
    pw = max((ow - 1) * sw + kw - iw, 0)
    return ph // 2, ph - ph // 2, pw // 2, pw - pw // 2


def conv(x, w, b, sh, sw, padding, depthwise, in_zp, w_zp, out_zp, m,
         relu6_hi, requant):
    ih, iw, ic = x.shape
    kh, kw = w.shape[1], w.shape[2]
    t, bo, l, r = pad_for(ih, iw, kh, kw, sh, sw, padding)
    xp = np.full((ih + t + bo, iw + l + r, ic), in_zp, dtype=np.int64)
    xp[t:t + ih, l:l + iw] = x
    oh = (xp.shape[0] - kh) // sh + 1
    ow = (xp.shape[1] - kw) // sw + 1
    win = np.lib.stride_tricks.sliding_window_view(xp, (kh, kw), axis=(0, 1))
    win = win[::sh, ::sw]                       # (oh, ow, ic, kh, kw)
    win = win.astype(np.int64) - in_zp
    if depthwise:
        wk = w[0].transpose(2, 0, 1).astype(np.int64) - w_zp   # (ic, kh, kw)
        acc = np.einsum("hwckl,ckl->hwc", win, wk) + b
    else:
        wk = w.astype(np.int64) - w_zp                          # (oc, kh, kw, ic)
        acc = np.einsum("hwckl,okli->hwo", win, wk.transpose(0, 1, 2, 3)) \
            if False else np.einsum("hwckl,oklc->hwo", win, wk) + b
    out = requant(acc.reshape(oh, ow, -1), m) + out_zp
    return np.clip(out, 0, relu6_hi if relu6_hi is not None else 255)


def main():
    path = SRC
    upto = None
    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        path = args.pop(0)
    if args and args[0] == "--upto":
        upto = int(args[1])

    buf = bytearray(open(path, "rb").read())
    m = Model.GetRootAsModel(buf, 0)
    g = m.Subgraphs(0)
    codes = [m.OperatorCodes(i).BuiltinCode() for i in range(m.OperatorCodesLength())]

    def arr(idx):
        t = g.Tensors(idx)
        b = m.Buffers(t.Buffer())
        if b.DataLength() == 0:
            return None
        raw = b.DataAsNumpy().tobytes()
        dt = {2: np.int32, 3: np.uint8, 9: np.int32}.get(t.Type(), np.uint8)
        return np.frombuffer(raw, dtype=dt).reshape(list(t.ShapeAsNumpy()))

    def qp(idx):
        q = g.Tensors(idx).Quantization()
        return float(q.ScaleAsNumpy()[0]), int(q.ZeroPointAsNumpy()[0])

    inp = int(g.Inputs(0))
    ish = list(g.Tensors(inp).ShapeAsNumpy())
    n = int(np.prod(ish))
    x0 = ((np.arange(n) * 7) % 251).reshape(ish[1:]).astype(np.int64)
    ref = {inp: x0.copy()}
    hw = {inp: x0.copy()}

    print("%-3s %-12s %-16s %-9s %s"
          % ("op", "kind", "shape", "channels", "what correct hardware scores"))
    for i in range(g.OperatorsLength()):
        op = g.Operators(i)
        code = codes[op.OpcodeIndex()]
        ins = list(op.InputsAsNumpy())
        o = int(op.Outputs(0))
        if code not in (BuiltinOperator.CONV_2D, BuiltinOperator.DEPTHWISE_CONV_2D):
            break
        dw = code == BuiltinOperator.DEPTHWISE_CONV_2D
        opt = DepthwiseConv2DOptions() if dw else Conv2DOptions()
        tab = op.BuiltinOptions()
        opt.Init(tab.Bytes, tab.Pos)
        sh, sw = opt.StrideH(), opt.StrideW()
        padding = opt.Padding()
        act = opt.FusedActivationFunction()
        w = arr(ins[1]).astype(np.int64)
        b = arr(ins[2]).astype(np.int64)
        si, zi = qp(ins[0]); sw_, zw = qp(ins[1]); so, zo = qp(o)
        mult = si * sw_ / so
        hi = 255
        if act == ActivationFunctionType.RELU6:
            hi = min(255, int(round(6.0 / so)) + zo)
        args_ = dict(sh=sh, sw=sw, padding=padding, depthwise=dw, in_zp=zi,
                     w_zp=zw, out_zp=zo, m=mult, relu6_hi=hi)
        ref[o] = conv(ref[ins[0]], w, b, requant=requant_tflite, **args_)
        hw[o] = conv(hw[ins[0]], w, b, requant=requant_hw, **args_)

        a, r = hw[o], ref[o]
        oc = a.shape[2]
        d = np.abs(a - r)
        good = int((d.max(axis=(0, 1)) <= 1).sum())
        print("%-3d %-12s %-16s %3d/%-5d %s"
              % (i, "depthwise" if dw else ("1x1" if w.shape[1] == 1 else "conv"),
                 "%dx%dx%d" % a.shape, good, oc,
                 "maxdiff %d, interior exact %5.2f%%"
                 % (d.max(), 100.0 * (d == 0).mean())))
        if upto is not None and i >= upto:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
