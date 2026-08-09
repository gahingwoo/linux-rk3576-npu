#!/usr/bin/env python3
"""
Compile pairs of vendor models that differ in exactly ONE thing.

The two captures this project has of the vendor coefficient buffer differ in
1682 of the 1936 bytes of the region still under investigation, but the two
models behind them also carry DIFFERENT WEIGHTS, because gen_geom.py randomises
per geometry. So nothing in that diff separates "varies with the kernel size"
from "varies with the weights", and the format cannot be read off it. This
builds pairs where only one variable moves.

Four pairs, base geometry ic=16 oc=128 80x80 stride 2, which is conv2d-cal, the
model that computes correctly:

  null    the same model compiled twice.
          THE CONTROL. If these two files are not identical then the toolkit is
          not deterministic and every diff below is contaminated. Run it first.

  wt      same geometry, different weights.   -> the weights-only signature
  k       same weights, kernel 5x5 vs 3x3.    -> the kernel-only signature
  oc      same weights, 128 vs 64 channels.   -> the channel-only signature

The kernel pair is the point of the exercise. The 5x5 model's weights are ZERO
outside the centre 3x3 and equal to the 3x3 model's weights inside it, so the
two compute the same function: the weight scale is set by the same maximum, the
calibrated output range is the same, the biases are the same, and every shared
tap quantizes to the same byte. The only thing left that can move is k.

Reading it: bytes that the k pair changes and the wt pair does not are
kernel-dependent. Bytes both pairs change are weight-dependent and were never
evidence about k.

Usage: sv_pairs.py [pair ...]     (default: all four)
Then:  rknn_blobs.py diff geom/sv_k5_rk3576.rknn geom/sv_k3_rk3576.rknn
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")

IC, OC, HW, S = 16, 128, 80, 2


def weights(rng, oc, ic, k):
    return (rng.randn(oc, ic, k, k) * 0.08).astype(np.float32)


def compile(name, w, bias, stride=S):
    """One model, from a weight array. Everything else is held fixed."""
    from rknn.api import RKNN

    os.makedirs(OUT, exist_ok=True)
    oc, ic, k, _ = w.shape
    onnx = f"{OUT}/{name}.onnx"
    rknn_path = f"{OUT}/{name}_rk3576.rknn"

    m = nn.Conv2d(ic, oc, k, stride=stride, padding=k // 2, bias=True)
    with torch.no_grad():
        m.weight.copy_(torch.from_numpy(w))
        m.bias.copy_(torch.from_numpy(bias))
    m.eval()
    torch.onnx.export(m, torch.randn(1, ic, HW, HW), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)

    # One calibration set for every model here, so the input scale is a
    # constant of the experiment rather than another moving part.
    calib = f"{OUT}/sv_calib.npy"
    if not os.path.exists(calib):
        np.save(calib, (np.arange(IC * HW * HW).reshape(1, IC, HW, HW)
                        % 251).astype(np.uint8))
    ds = f"{OUT}/sv_dataset.txt"
    open(ds, "w").write(os.path.abspath(calib) + "\n")

    r = RKNN(verbose=False)
    # Same config gen_geom.py used, so these stay comparable with the two
    # models the board capture came from.
    r.config(target_platform="rk3576")
    assert r.load_onnx(model=onnx) == 0, f"{name}: load_onnx"
    assert r.build(do_quantization=True, dataset=ds) == 0, f"{name}: build"
    assert r.export_rknn(rknn_path) == 0, f"{name}: export"
    r.release()
    print(f"OK {name}: oc={oc} ic={ic} k={k} s={stride} -> {rknn_path}",
          flush=True)


def pair_null():
    rng = np.random.RandomState(1234)
    w = weights(rng, OC, IC, 5)
    b = (rng.randn(OC) * 0.05).astype(np.float32)
    compile("sv_null_a", w, b)
    compile("sv_null_b", w, b)


def pair_wt():
    """Same shape, different values. The weights-only signature."""
    w1 = weights(np.random.RandomState(1234), OC, IC, 5)
    w2 = weights(np.random.RandomState(5678), OC, IC, 5)
    # Hold the tensor maximum equal so the weight scale is not a second
    # variable riding along with the values.
    w2 *= float(np.abs(w1).max()) / float(np.abs(w2).max())
    b = (np.random.RandomState(99).randn(OC) * 0.05).astype(np.float32)
    compile("sv_wt_a", w1, b)
    compile("sv_wt_b", w2, b)


def pair_k():
    """Same weights, 5x5 with a zero ring vs the 3x3 it contains."""
    rng = np.random.RandomState(1234)
    w3 = weights(rng, OC, IC, 3)
    b = (rng.randn(OC) * 0.05).astype(np.float32)
    w5 = np.zeros((OC, IC, 5, 5), dtype=np.float32)
    w5[:, :, 1:4, 1:4] = w3
    # 80 -> 40 either way: k=5 pad 2 stride 2, k=3 pad 1 stride 2.
    compile("sv_k5", w5, b)
    compile("sv_k3", w3, b)


def pair_oc():
    """Same first 64 channels, 128 vs 64 outputs."""
    rng = np.random.RandomState(1234)
    w = weights(rng, OC, IC, 5)
    b = (rng.randn(OC) * 0.05).astype(np.float32)
    # Damp the channels only the big model has, so the shared 64 keep setting
    # both the weight maximum and the calibrated output range.
    w[64:] *= 0.25
    b[64:] *= 0.25
    compile("sv_oc128", w, b)
    compile("sv_oc64", w[:64].copy(), b[:64].copy())


PAIRS = {"null": pair_null, "wt": pair_wt, "k": pair_k, "oc": pair_oc}

if __name__ == "__main__":
    for p in (sys.argv[1:] or list(PAIRS)):
        PAIRS[p]()
