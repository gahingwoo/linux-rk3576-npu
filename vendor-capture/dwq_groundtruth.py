#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Find the toolkit's OWN quantised weights inside the .rknn, so the capture can
be read against bytes the toolkit wrote rather than bytes this script guessed.

dwweight_locate.py's control reached 89.75 percent, not 100, which says the
weights are where it pointed but that the int8 computed here is not byte for
byte what the toolkit produced: a rounding rule, a slightly different scale, or
padding inside the window. Guessing at that is exactly the kind of unanchored
sweep this project keeps having to withdraw, so anchor it instead.

Every byte vector in the .rknn is scored by byte-histogram overlap against the
int8 computed here, permutation invariant. The vector that scores highest IS
the weight tensor, and the difference between it and the local computation is
then a small, inspectable thing.
"""
import os
import struct
import sys

import numpy as np

from rknn_blobs import vectors


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    return b, wdw, wrg


def q_perchannel(w):
    sc = np.abs(w).max(axis=(1, 2, 3)) / 127.0
    return np.clip(np.rint(w / sc[:, None, None, None]), -128,
                   127).astype(np.int8), sc


def hist(v):
    return np.bincount(np.asarray(v, dtype=np.uint8).astype(np.int64),
                       minlength=256)


def report(path, w, tag):
    print(f"\n=== {tag}: {os.path.basename(path)} ===")
    q, sc = q_perchannel(w)
    hq = hist(q.reshape(-1).view(np.uint8))
    n = q.size
    d, vs = vectors(path)
    rows = []
    for off, L, _blob in vs:
        v = np.frombuffer(d, dtype=np.uint8, count=L, offset=off)
        if L < n:
            continue
        # best n-byte window inside this vector, permutation invariant
        best = 0
        bo = 0
        for s in range(0, L - n + 1, max(1, (L - n) // 64 or 1)):
            sc_ = np.minimum(hist(v[s:s + n]), hq).sum()
            if sc_ > best:
                best, bo = sc_, s
        rows.append((best / n, off, L, bo))
    rows.sort(reverse=True)
    for pct, off, L, bo in rows[:6]:
        print(f"  {pct*100:6.2f}%  vector @0x{off:06x} len {L:6d}  window +{bo}")
    return rows


if __name__ == "__main__":
    b, wdw, wrg = known()
    report("geom/sv_rgu_rk3576.rknn", wrg, "sv_rgu regular")
    report("geom/sv_dwu_rk3576.rknn", wdw, "sv_dwu depthwise")
