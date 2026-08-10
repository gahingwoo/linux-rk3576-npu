#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Round 54, offline. Locate the DEPTHWISE WEIGHTS in the vendor capture.

The whole coefficient chain has now been excluded for depthwise: the 48-byte
record, the fp16 scale table, the float bias, the per-channel B, six operand
words and the old float surface all leave dwconv at six distinct output values.
So the next thing that can be wrong is the other buffer the layer reads, the
WEIGHTS, and the capture of sv_dwu is the first look this project has ever had
at what the vendor actually hands the hardware for a depthwise layer.

The pair is sv_rgu / sv_dwu from `sv_pairs.py dw`: ic = oc = 32 at 112x112,
k = 3, s = 1, one calibration set each, only `groups` differing. Both weight
tensors are generated from RandomState(7) here, so the exact int8 the toolkit
must have produced is computable.

The test is PERMUTATION INVARIANT, because the point of a hardware weight
buffer is that it is shuffled: for every window the size of the weight tensor,
compare the window's byte histogram with the histogram of the expected int8
values and report the best overlap. A shuffle of the weights, whatever the
shuffle is, scores 100 percent. Padding or interleaving with a constant costs
only the padded bytes.

DECISION RULE, written before the run:

  control    sv_rgu's weights must score near 100 percent somewhere. A regular
             conv is the case this project already computes correctly, so if
             the search cannot find ITS weights the search is wrong and
             nothing it says about sv_dwu counts.
  found      report the buffer, offset and score for both, then go after the
             ordering inside the window.
  not found  the depthwise weights are not in the captured buffers as int8 at
             the scale the toolkit would use, which is itself an answer.
"""
import glob
import os
import sys

import numpy as np


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    return b, wdw, wrg


def quantisations(w):
    """The encodings the toolkit plausibly writes, as uint8 byte values."""
    out = {}
    sc_c = np.abs(w).max(axis=(1, 2, 3)) / 127.0
    qc = np.clip(np.rint(w / sc_c[:, None, None, None]), -128, 127)
    sc_t = np.abs(w).max() / 127.0
    qt = np.clip(np.rint(w / sc_t), -128, 127)
    for name, q in (("per-channel int8", qc), ("per-tensor int8", qt)):
        v = q.astype(np.int8).reshape(-1).view(np.uint8)
        out[name] = v
        out[name.replace("int8", "uint8 +128")] = (q + 128).astype(np.uint8).reshape(-1)
    return out


def hist(v):
    return np.bincount(v.astype(np.int64), minlength=256)


def best_window(raw, want_hist, n):
    """Best byte-histogram overlap between any n-byte window and want_hist."""
    N = len(raw)
    if N < n:
        return None
    # counts[v] over a sliding window, from per-value cumulative sums taken in
    # chunks so the whole 256 x N table never exists at once.
    best = (-1, -1)
    total = np.zeros(N - n + 1, dtype=np.int32)
    for lo in range(0, 256, 32):
        vals = np.arange(lo, min(lo + 32, 256))
        eq = (raw[None, :] == vals[:, None]).astype(np.int32)
        cs = np.cumsum(eq, axis=1)
        win = cs[:, n - 1:] - np.concatenate(
            [np.zeros((len(vals), 1), dtype=np.int32), cs[:, :-n]], axis=1)
        total += np.minimum(win, want_hist[vals][:, None]).sum(axis=0)
    k = int(np.argmax(total))
    best = (int(total[k]), k)
    return best


def scan(path, w, tag):
    print(f"\n=== {tag} ===")
    n = w.size
    enc = quantisations(w)
    rows = []
    for f in sorted(glob.glob(os.path.join(path, "*.bin"))):
        raw = np.frombuffer(open(f, "rb").read(), dtype=np.uint8)
        if len(raw) < n:
            continue
        for name, v in enc.items():
            r = best_window(raw, hist(v), n)
            if r is None:
                continue
            score, off = r
            rows.append((score / n, os.path.basename(f), name, off))
    rows.sort(reverse=True)
    for pct, fn, name, off in rows[:8]:
        print(f"  {pct*100:6.2f}%  {fn:12s} @0x{off:06x}  {name}")
    return rows[0][0] if rows else 0.0


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    b, wdw, wrg = known()
    print("CONTROL FIRST. If the regular conv's weights are not located, the "
          "depthwise reading below is void.")
    ok = scan(os.path.join(root, "sv_rgu"), wrg, "sv_rgu (control, regular)")
    if ok < 0.95:
        print(f"\n!! CONTROL only reached {ok*100:.1f}% -- read nothing below.")
    scan(os.path.join(root, "sv_dwu"), wdw, "sv_dwu (depthwise)")
