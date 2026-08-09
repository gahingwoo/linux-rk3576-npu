#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Decide what the uint16 per-channel table at coef 0x400 actually holds.

Decoding it as fp16 puts it within a few percent of each channel's weight scale,
which is suggestive and nothing more: it is consistently a little SMALLER than
max|w_c|/127, so it is not that expression, and "close to the right magnitude"
is the kind of agreement that has already misled this project twice.

So move one channel and see if one entry moves. Channel 7 is multiplied by 2 and
channel 11 by 1/2, everything else untouched.

  if it is a per-channel weight scale, entry 7 doubles, entry 11 halves, and the
  other 126 entries are unchanged
  if the other entries move, the value is not per-channel and the fp16 reading
  is a coincidence of magnitude
  if nothing moves, it is not about the weights at all

Usage: sv_scaleprobe.py [build]     (build recompiles, otherwise just compares)
"""
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rknn_blobs import chunks  # noqa: E402

SCR = os.path.dirname(os.path.abspath(__file__))
IC, OC, HW, S, K = 16, 128, 80, 2, 5
UP, DOWN = 7, 11


def base_weights():
    rng = np.random.RandomState(1234)
    w = (rng.randn(OC, IC, K, K) * 0.08).astype(np.float32)
    b = (rng.randn(OC) * 0.05).astype(np.float32)
    return w, b


if len(sys.argv) > 1 and sys.argv[1] == "build":
    from sv_pairs import compile as build
    w, b = base_weights()
    build("sv_sc_base", w, b)
    w2 = w.copy()
    w2[UP] *= 2.0
    w2[DOWN] *= 0.5
    build("sv_sc_moved", w2, b)

_, per_a = chunks(f"{SCR}/geom/sv_sc_base_rk3576.rknn", OC)
_, per_b = chunks(f"{SCR}/geom/sv_sc_moved_rk3576.rknn", OC)
a = np.frombuffer(per_a[2], dtype=np.float16).astype(np.float64)
b = np.frombuffer(per_b[2], dtype=np.float16).astype(np.float64)

moved = [c for c in range(OC) if a[c] != b[c]]
print(f"entries that changed: {moved}")
print(f"  expected exactly [{UP}, {DOWN}]")
for c in (UP, DOWN):
    print(f"  channel {c:3d}: {a[c]:.6g} -> {b[c]:.6g}   ratio {b[c]/a[c]:.4f}"
          f"   (expected {2.0 if c == UP else 0.5})")
others = [c for c in moved if c not in (UP, DOWN)]
ok = set(moved) == {UP, DOWN} and abs(b[UP]/a[UP] - 2) < 0.01 \
    and abs(b[DOWN]/a[DOWN] - 0.5) < 0.01
print(f"  untouched channels that moved anyway: {len(others)}")
print("VERDICT:", "per-channel weight scale, stored as fp16" if ok
      else "NOT a clean per-channel weight scale, see the numbers above")
