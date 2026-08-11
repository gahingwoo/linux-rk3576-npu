#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What layout does the vendor use for a depthwise with MANY channels?

Round 68 measured the fault exactly. With the live tap at the same position in
every channel, the channels that produce anything are one contiguous run that
moves with the tap:

    tap   0    1    2    3    4    5    6    7    8
    from  0   64  192  320  448  512  640  768  896
    to  127  255  383  511  575  703  831  959  991

Inverted, each output channel can reach only ONE OR TWO of its nine spatial
blocks, and which one advances by 1 every 128 channels. A depthwise needs all
nine, so nothing computes.

mesa lays the buffer out tap major with a block stride of 2C bytes, which is
64 bytes at 32 channels and 2048 at 1024. At 32 channels the nine blocks span
576 bytes and every channel reaches all of them, which is why every depthwise
in this project up to now has worked and why fifteen rounds of coefficient work
never touched this.

The 32 channel layout is not a guess: it was checked against the vendor's own
576 bytes, 288 of 288 weight lanes. The question is what the vendor does when
the block stride would grow past the hardware's reach, and the depthwise
WEIGHTS are in the .rknn even though the coefficient table is not. So compile
one and look. No board.

The pair is the same single variable idea as sv_pairs.py: identical geometry,
identical calibration, only the channel count moving, so the block stride is
the only thing that can differ.
"""
import os
import sys

import numpy as np

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, "geom")


def build(name, channels, hw, k=3):
    import torch
    import torch.nn as nn
    from rknn.api import RKNN

    os.makedirs(OUT, exist_ok=True)
    onnx = f"{OUT}/{name}.onnx"
    out = f"{OUT}/{name}_rk3576.rknn"

    rng = np.random.RandomState(11)
    w = (rng.randn(channels, 1, k, k) * 0.08).astype(np.float32)
    b = (rng.randn(channels) * 0.05).astype(np.float32)

    m = nn.Conv2d(channels, channels, k, stride=1, padding=k // 2,
                  groups=channels, bias=True)
    with torch.no_grad():
        m.weight.copy_(torch.from_numpy(w))
        m.bias.copy_(torch.from_numpy(b))
    m.eval()
    torch.onnx.export(m, torch.randn(1, channels, hw, hw), onnx,
                      input_names=["input"], output_names=["output"],
                      opset_version=12)

    calib = f"{OUT}/{name}_c.npy"
    np.save(calib, (np.arange(channels * hw * hw).reshape(1, channels, hw, hw)
                    % 251).astype(np.uint8))
    ds = f"{OUT}/{name}_d.txt"
    open(ds, "w").write(os.path.abspath(calib) + "\n")

    r = RKNN(verbose=False)
    r.config(target_platform="rk3576", compress_weight=False)
    assert r.load_onnx(model=onnx) == 0, f"{name}: load_onnx"
    assert r.build(do_quantization=True, dataset=ds) == 0, f"{name}: build"
    assert r.export_rknn(out) == 0, f"{name}: export"
    r.release()
    print(f"OK {name}: {channels} channels at {hw}x{hw} -> {out}", flush=True)
    return out, w


def inspect(path, channels, k=3):
    """Find the weight vector and say what its spatial block stride is."""
    from rknn_blobs import vectors

    d, vs = vectors(path)
    taps = k * k
    # mesa's layout would be taps * DIV_ROUND_UP(channels, 2) * 4 bytes.
    mesa_len = taps * ((channels + 1) // 2) * 4
    print(f"\n=== {os.path.basename(path)}: {channels} channels ===")
    print(f"  mesa would write {mesa_len} bytes, "
          f"block stride {mesa_len // taps}")
    cands = [(off, L) for off, L, _ in vs if taps <= L <= mesa_len * 4]
    cands.sort(key=lambda x: abs(x[1] - mesa_len))
    for off, L in cands[:6]:
        note = ""
        if L == mesa_len:
            note = "  <- exactly mesa's size"
        elif L % taps == 0:
            note = f"  ({L // taps} bytes per spatial block)"
        print(f"    vector at 0x{off:06x} length {L:7d}"
              f"   {L / channels:8.3f} bytes per channel{note}")


def main():
    hw = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    for ch in (32, 128, 256, 1024):
        name = f"dwbig_{ch}"
        path = f"{OUT}/{name}_rk3576.rknn"
        if not os.path.exists(path):
            try:
                build(name, ch, hw)
            except Exception as e:                       # noqa: BLE001
                print(f"  {name}: build failed: {e}")
                continue
        inspect(path, ch)


if __name__ == "__main__":
    main()
