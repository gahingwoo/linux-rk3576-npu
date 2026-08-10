#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Pin the toolkit's quantisation rule, or show that the candidate vector is not
the weights at all.

dwq_layout.py killed the easy reading: the 9216 byte vector in sv_rgu, which is
exactly the element count of the regular conv's weight tensor, matches plain
per-channel int8 in OIHW order for 0.42 percent of its elements. Either the
order is shuffled, or the quantisation rule is not the one assumed, or the
vector is not the weights.

Multiset equality separates those. Sorting the whole tensor throws the ordering
away entirely, so if the values are right and merely shuffled, the sorted bytes
of the vector and the sorted bytes of the computed int8 are IDENTICAL. A sweep
of plausible rules is then a fair test rather than a fishing trip, because
every rule is scored the same way and the score has a ceiling that a wrong
vector cannot reach.

DECISION RULE, written before the run:
  100 percent for some rule    that rule is the toolkit's, and the remaining
                               question is only the ordering
  high but not 100             right vector, rounding differs at ties
  nothing above about 60       the vector is not the weight tensor, and the
                               weights are somewhere else (or compressed)
"""
import numpy as np

from rknn_blobs import vectors


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    return b, wdw, wrg


def rules(w):
    """Candidate quantisations, each as a uint8 byte array of w.size bytes."""
    oc = w.shape[0]
    flat = w.reshape(oc, -1)
    out = {}
    amax = np.abs(flat).max(axis=1, keepdims=True)
    for div, dn in ((127.0, "127"), (128.0, "128")):
        s = amax / div
        q = np.rint(flat / s)
        out[f"per-channel sym /{dn}"] = np.clip(q, -128, 127)
    st = np.abs(flat).max() / 127.0
    out["per-tensor sym /127"] = np.clip(np.rint(flat / st), -128, 127)
    lo = flat.min(axis=1, keepdims=True)
    hi = flat.max(axis=1, keepdims=True)
    s = (hi - lo) / 255.0
    zp = np.rint(-lo / s) - 128
    out["per-channel asym"] = np.clip(np.rint(flat / s) + zp, -128, 127)
    # floor-based rounding, which some toolkits use for symmetric weights
    s = amax / 127.0
    out["per-channel sym, floor(x+0.5)"] = np.clip(np.floor(flat / s + 0.5),
                                                   -128, 127)
    return {k: v.astype(np.int8).reshape(-1).view(np.uint8)
            for k, v in out.items()}


def overlap(a, b):
    ha = np.bincount(a.astype(np.int64), minlength=256)
    hb = np.bincount(b.astype(np.int64), minlength=256)
    return np.minimum(ha, hb).sum() / len(a)


def main():
    b, wdw, wrg = known()
    for tag, path, w, n in (("sv_rgu regular", "geom/sv_rgu_rk3576.rknn", wrg, 9216),
                            ("sv_dwu depthwise", "geom/sv_dwu_rk3576.rknn", wdw, 288)):
        print(f"\n=== {tag}: every vector of at least {n} bytes ===")
        d, vs = vectors(path)
        R = rules(w)
        rows = []
        for off, L, _ in vs:
            if L < n or L > 1 << 17:
                continue
            v = np.frombuffer(d, dtype=np.uint8, count=L, offset=off)
            for rname, q in R.items():
                # best window, coarse then refined around the winner
                best, bo = -1.0, 0
                step = max(1, (L - n) // 128 or 1)
                for s0 in range(0, L - n + 1, step):
                    sc = overlap(v[s0:s0 + n], q)
                    if sc > best:
                        best, bo = sc, s0
                for s0 in range(max(0, bo - step), min(L - n, bo + step) + 1):
                    sc = overlap(v[s0:s0 + n], q)
                    if sc > best:
                        best, bo = sc, s0
                rows.append((best, off, L, bo, rname))
        rows.sort(reverse=True)
        for sc, off, L, bo, rname in rows[:6]:
            print(f"  {sc*100:6.2f}%  @0x{off:06x} len {L:6d} +{bo:<6d} {rname}")


if __name__ == "__main__":
    main()
