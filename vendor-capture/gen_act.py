#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Compile the same int8 convolution WITH and WITHOUT a fused activation, so the
register that turns the hardware's ReLU off can be read off a desktop.

Why this exists. Every Teflon model carries a ReLU, so Mesa has never had to
switch one off, and charsiu's matmul output is clamped into 0 to 127 before the
output offset is applied: the bottom of that clamp is a ReLU on a projection
whose result is signed. Sweeping registers on the board to find the enable is
several rounds; the vendor compiler answers it in one run, in the right
precision, on this desktop.

The RK3588 way of reading this was tried first and does not transfer. The
mobilenetv2 .rknn on disk splits cleanly into a ReLU6 group and a linear group
that differ in exactly five DPU registers, but that model is FP16 (0x40b0 =
0x00010001 and 0x40b4 = 0 on 250 of its 274 convolutions is an identity
requant), so its clamp values are floats and say nothing about where an int8
clamp lives. Hence: compile int8, here, with the activation as the only change.

THE CONTROL. A third model, linear again but with different weights, separates
the activation registers from the data dependent ones. A register only counts if
it differs between relu and linear AND agrees between the two linears. Without
it every quantisation register would look like a candidate.

Usage: gen_act.py            build all three and print the diff
       gen_act.py --diff     diff what is already built
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")

IC, OC, HW, K = 64, 64, 8, 1

#  name        relu   seed  spatial
MODELS = [
    ("a_relu", True, 0, HW),
    ("a_lin", False, 0, HW),
    ("a_lin2", False, 7, HW),   # the control: linear, different data
    # charsiu's own shape: one row, one pixel, 64 to 64. Same conv the runtime
    # submits, compiled by the vendor, so the whole stream can be diffed and not
    # just the three activation registers.
    ("a_lin_m1", False, 0, 1),
]


def build(name, relu, seed, hw):
    from rknn.api import RKNN

    os.makedirs(OUT, exist_ok=True)
    onnx = f"{OUT}/{name}.onnx"
    rknn_path = f"{OUT}/{name}_rk3576.rknn"

    rng = np.random.RandomState(seed)
    conv = nn.Conv2d(IC, OC, K, stride=1, padding=K // 2, bias=True)
    with torch.no_grad():
        conv.weight.copy_(torch.from_numpy(
            (rng.randn(*conv.weight.shape) * 0.08).astype(np.float32)))
        conv.bias.copy_(torch.from_numpy((rng.randn(OC) * 0.05).astype(np.float32)))
    m = nn.Sequential(conv, nn.ReLU()) if relu else nn.Sequential(conv)
    m.eval()
    torch.onnx.export(m, torch.randn(1, IC, hw, hw), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)

    calib = f"{OUT}/{name}_calib.npy"
    np.save(calib, (np.arange(IC * hw * hw).reshape(1, IC, hw, hw) % 251).astype(np.uint8))
    ds = f"{OUT}/{name}_dataset.txt"
    open(ds, "w").write(os.path.abspath(calib) + "\n")

    r = RKNN(verbose=False)
    r.config(target_platform="rk3576")
    if r.load_onnx(model=onnx) != 0:
        print(f"{name}: load_onnx failed"); return
    if r.build(do_quantization=True, dataset=ds) != 0:
        print(f"{name}: build failed"); return
    if r.export_rknn(rknn_path) != 0:
        print(f"{name}: export failed"); return
    r.release()
    print(f"OK {name}: relu={relu} seed={seed} hw={hw} -> {rknn_path}")


def regs_of(path):
    sys.path.insert(0, "/home/parallels/Desktop/charsiu/tools")
    from rkllm_regcmd import streams, decode, geometry
    for _, ws in streams(path):
        r = decode(ws)
        g = geometry(r)
        if g and g["ic"] == IC and g["oc"] == OC:
            return r
    return None


def diff():
    TAG = {0x201: "CNA", 0x801: "CORE", 0x1001: "DPU", 0x2001: "RDMA"}
    a = regs_of(f"{OUT}/a_relu_rk3576.rknn")
    b = regs_of(f"{OUT}/a_lin_rk3576.rknn")
    c = regs_of(f"{OUT}/a_lin2_rk3576.rknn")
    if not (a and b and c):
        print("missing streams: relu=%s lin=%s lin2=%s"
              % (bool(a), bool(b), bool(c)))
        return 1
    print("relu %d registers, linear %d, control %d\n" % (len(a), len(b), len(c)))
    print("  %-5s %-6s %-10s %-10s %-10s" % ("", "reg", "relu", "linear", "control"))
    cand = 0
    for k in sorted(set(a) | set(b), key=lambda x: (x[0], x[1])):
        va, vb, vc = a.get(k), b.get(k), c.get(k)
        if va == vb:
            continue
        # a candidate only if the two linears agree: otherwise it is data
        mark = "CANDIDATE" if vb == vc else "data dependent"
        if vb == vc:
            cand += 1
        print("  %-5s %04x   %-10s %-10s %-10s  %s"
              % (TAG.get(k[0], "?"), k[1],
                 "--" if va is None else "%08x" % va,
                 "--" if vb is None else "%08x" % vb,
                 "--" if vc is None else "%08x" % vc, mark))
    print("\n  %d candidates" % cand)
    return 0


if __name__ == "__main__":
    if "--diff" not in sys.argv:
        for m in MODELS:
            build(*m)
    sys.exit(diff())
