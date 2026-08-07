#!/usr/bin/env python3
"""
Compile vendor .rknn files at chosen conv geometries, so the CNA registers mesa
fills from a hardcoded ladder can be read at geometries nobody ever captured.

rkt_regcmd.c sets 0x1014, 0x1018, 0x1040 and 0x1080 from `s == 2 ? A : B`
constants fitted to the few captures this project has, and conv2d-cal, the one
model that computes correctly, is the geometry the stride-2 branch was fitted to.
For a stride-1 regular conv mesa emits CNA 0x1080 = 0, and no vendor .rknn on
disk contains a 0 there.

The toolkit's tflite frontend is not supported on arm64, so these go through
ONNX. Weights and quantization do not have to match any particular model: the
four registers under test are configuration, not data.

Usage: gen_geom.py           (builds the whole table)
       gen_geom.py <name>    (one entry)
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")

#  name          ic    oc    hw    k  stride  groups   mirrors
GEOMS = [
    ("g_cal",     16,  128,   80,  5,   2,     1),   # conv2d-cal, the one that works
    ("g_cal_s1",  16,  128,   80,  5,   1,     1),   # cal_s1, same but stride 1
    ("g_md003",   16,   16,  160,  1,   1,     1),   # md003
    ("g_md003s2", 16,   16,  160,  1,   2,     1),   # md003_s2
    ("g_pw2",     32,   64,  112,  1,   1,     1),   # MobileNet op2
    ("g_pw24",   512, 1024,    7,  1,   1,     1),   # MobileNet op24
    ("g_dw1",     32,   32,  112,  3,   1,    32),   # MobileNet op1, depthwise
    ("g_k3s1",    16,   16,   80,  3,   1,     1),   # 3x3 stride 1, small
]


def build(name, ic, oc, hw, k, s, groups):
    from rknn.api import RKNN

    os.makedirs(OUT, exist_ok=True)
    onnx = f"{OUT}/{name}.onnx"
    rknn_path = f"{OUT}/{name}_rk3576.rknn"

    rng = np.random.RandomState(0)
    m = nn.Conv2d(ic, oc, k, stride=s, padding=k // 2, groups=groups, bias=True)
    with torch.no_grad():
        m.weight.copy_(torch.from_numpy(
            (rng.randn(*m.weight.shape) * 0.08).astype(np.float32)))
        m.bias.copy_(torch.from_numpy((rng.randn(oc) * 0.05).astype(np.float32)))
    m.eval()
    torch.onnx.export(m, torch.randn(1, ic, hw, hw), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)

    calib = f"{OUT}/{name}_calib.npy"
    np.save(calib, (np.arange(ic * hw * hw).reshape(1, ic, hw, hw) % 251).astype(np.uint8))
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
    print(f"OK {name}: ic={ic} oc={oc} {hw}x{hw} k={k} s={s} groups={groups} "
          f"-> {rknn_path}")


for g in GEOMS:
    if len(sys.argv) > 1 and g[0] != sys.argv[1]:
        continue
    build(*g)
