#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Decode the captured vendor coefficient buffers for the depthwise pair.

The pair is sv_rgu and sv_dwu from `sv_pairs.py dw`: ic = oc = 32 at 112x112,
k=3, s=1, one calibration set, only `groups` differing, and their weights and
biases are generated here so they are known exactly. That is what makes a
capture decodable rather than a hex dump to stare at.

The method is the one that already worked on the .rknn files, including the two
oracle bugs it caught. Every per-channel column in every captured buffer, under
flat and BLOCKED layouts, correlated against the known bias, the known
per-channel weight sum, and the per-channel-scaled forms, because
`A = bias - (in_zp - 0x80) * sw` and with per-channel quantisation A is not
proportional to either term alone.

⚠ sv_rgu is the POSITIVE CONTROL and is checked first. Its A column must come
back correlating with the weight sum, as it does in the .rknn at +0.9972. If it
does not, the capture is not what this script thinks it is and nothing sv_dwu
says can be read.

Usage: dwcoef_decode.py <rgu_capture_dir> <dwu_capture_dir>
"""
import glob
import os
import struct
import sys

import numpy as np


def refs():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    out = {"bias": b.astype(float)}
    for tag, w in (("dw", wdw), ("rg", wrg)):
        sw = w.sum(axis=(1, 2, 3)).astype(float)
        sc = (np.abs(w).max(axis=(1, 2, 3)) / 127.0).astype(float)
        out[f"{tag}: weight sum"] = sw
        out[f"{tag}: bias/wt_sc_c"] = b / sc
        out[f"{tag}: sw/wt_sc_c"] = sw / sc
        for c in (1.0, -1.0, 2.0, -2.0):
            out[f"{tag}: bias{c:+.0f}*sw"] = b + c * sw
    return out


def columns(raw, n=32):
    """Yield (label, values) for every plausible per-channel column."""
    N = len(raw)
    for dt, esz in ((np.int32, 4), (np.int16, 2), (np.float32, 4)):
        for block, G in ((64, 8), (64, 16), (32, 8), (32, 4), (128, 16), (0, 1)):
            for elem in (2, 4):
                if elem != esz or (block and G * elem > block):
                    continue
                stride = elem if block == 0 else None
                for base in range(0, (block or 16), 2):
                    if block:
                        idx = np.array([base + (i // G) * block + (i % G) * elem
                                        for i in range(n)])
                    else:
                        idx = base + np.arange(n) * elem
                    span = idx[-1] + esz
                    if span >= N:
                        continue
                    starts = np.arange(0, N - span, 2)
                    if not len(starts):
                        continue
                    offs = starts[:, None] + idx[None, :]
                    buf = np.zeros((len(starts), n, esz), dtype=np.uint8)
                    for k in range(esz):
                        buf[:, :, k] = raw[offs + k]
                    X = buf.reshape(len(starts), n * esz).view(dt)
                    X = X.reshape(len(starts), n).astype(np.float64)
                    X[~np.isfinite(X)] = 0.0
                    yield (dt.__name__, block, G, elem, base), starts, X


def scan(path, ref_filter, label):
    R = refs()
    hits = []
    for f in sorted(glob.glob(os.path.join(path, "*.bin"))):
        raw = np.frombuffer(open(f, "rb").read(), dtype=np.uint8)
        if len(raw) < 256:
            continue
        for meta, starts, X in columns(raw):
            Xc = X - X.mean(1, keepdims=True)
            xs = np.sqrt((Xc ** 2).sum(1))
            for rn, rv in R.items():
                if ref_filter not in rn and rn != "bias":
                    continue
                yc = rv - rv.mean()
                ys = np.sqrt((yc ** 2).sum())
                with np.errstate(invalid="ignore", divide="ignore"):
                    c = np.nan_to_num((Xc @ yc) / (xs * ys))
                k = int(np.argmax(np.abs(c)))
                if abs(c[k]) > 0.98:
                    hits.append((abs(c[k]), os.path.basename(f),
                                 int(starts[k]), meta, rn, float(c[k])))
    hits.sort(reverse=True)
    print(f"  {label}: {len(hits)} per-channel columns above 0.98")
    seen = set()
    for a, fn, off, meta, rn, c in hits:
        if (fn, rn) in seen:
            continue
        seen.add((fn, rn))
        print(f"    {fn} @0x{off:05x}  {meta}  vs {rn:22s} corr {c:+.4f}")
        if len(seen) >= 10:
            break
    if not hits:
        print("    NONE")
    return bool(hits)


rgu, dwu = sys.argv[1], sys.argv[2]
print("CONTROL FIRST. The regular capture must decode, or nothing below counts.")
ok = scan(rgu, "rg:", "sv_rgu (control)")
if not ok:
    print("\n⚠ CONTROL FAILED: the capture is not what this script expects, so "
          "the depthwise result below cannot be read. Fix this first.")
scan(dwu, "dw:", "sv_dwu depthwise")
