#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Compare the single-variable pairs from sv_pairs.py, on the parts of the vendor
coefficient buffer that a recompile does not change.

The null pair is the control and it is checked first. If two compiles of one
identical model do not agree on a chunk, that chunk carries no information about
any model property and this script refuses to report on it.

Usage: sv_compare.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rknn_blobs import chunks  # noqa: E402

SCR = os.path.dirname(os.path.abspath(__file__))
G = os.path.join(SCR, "geom")


def get(name, oc):
    abc, per = chunks(f"{G}/{name}_rk3576.rknn", oc)
    return abc, per


def cmp_chunk(x, y, label):
    if x is None or y is None:
        print(f"    {label}: NOT FOUND in one of the two")
        return None
    if x[1] != y[1]:
        print(f"    {label}: different sizes, {x[1]} vs {y[1]} bytes")
        return None
    n = sum(1 for i in range(x[1]) if x[2][i] != y[2][i])
    print(f"    {label}: {n}/{x[1]} bytes differ"
          f"{'  (IDENTICAL)' if n == 0 else ''}")
    return n


def pair(name, a, b, oca, ocb):
    print(f"\n{name}:  {a} vs {b}")
    abca, pera = get(a, oca)
    abcb, perb = get(b, ocb)
    r1 = cmp_chunk(abca, abcb, "coef 0x000 A/B/C  ")
    r2 = cmp_chunk(pera, perb, "coef 0x400 per-oc ")
    return r1, r2


print("CONTROL first. Two compiles of one identical model:")
ctl = pair("null", "sv_null_a", "sv_null_b", 128, 128)
if ctl != (0, 0):
    print("\n⚠ CONTROL FAILED: the toolkit does not reproduce these chunks "
          "either, so nothing below can be attributed to a model property.")
    sys.exit(1)
print("\n  control passes: both chunks survive a recompile unchanged, so a "
      "difference below is caused by the variable that moved.")

pair("weights only", "sv_wt_a", "sv_wt_b", 128, 128)
pair("kernel only (5x5 zero-ring vs the 3x3 it contains)",
     "sv_k5", "sv_k3", 128, 128)
pair("channels only", "sv_oc128", "sv_oc64", 128, 64)

# The per-oc table read as uint16, to see what it actually holds.
print("\nper-oc table as uint16, first 8 entries:")
for nm, oc in (("sv_k5", 128), ("sv_k3", 128), ("sv_wt_a", 128),
               ("sv_wt_b", 128), ("sv_oc64", 64)):
    _, per = get(nm, oc)
    if per is None:
        continue
    v = struct.unpack_from("<%dH" % min(8, per[1] // 2), per[2], 0)
    uniq = len(set(struct.unpack("<%dH" % (per[1] // 2), per[2])))
    print(f"  {nm:10s} {list(v)}  ({uniq} distinct of {per[1]//2})")
