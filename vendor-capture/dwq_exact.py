#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
The regular conv's weights are pinned exactly; now pin the depthwise ones.

dwq_rule.py settled the control: the 9216 byte vector at 0x0091c0 in sv_rgu is
the weight tensor, and the toolkit quantises it PER OUTPUT CHANNEL and
ASYMMETRICALLY, min and max of the channel mapped onto the 256 codes. That rule
reproduces the stored bytes as a multiset perfectly, 9216 out of 9216.

Two things follow, and both are checked here rather than assumed:

  1. whether the stored order is plain OIHW, element for element, which decides
     whether the .rknn holds a hardware layout or a plain tensor;
  2. what the depthwise vector is, given that the same rule reaches only 55.9
     percent on it. 576 bytes for a 288 element tensor is the shape of the
     question.

Every depthwise candidate is scored the same permutation invariant way as the
control, and the control is rescored alongside so the ceiling is visible.
"""
import numpy as np

from rknn_blobs import vectors


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    return b, wdw, wrg


def asym_perchannel(flat):
    lo = flat.min(axis=1, keepdims=True)
    hi = flat.max(axis=1, keepdims=True)
    s = (hi - lo) / 255.0
    zp = np.rint(-lo / s) - 128
    q = np.clip(np.rint(flat / s) + zp, -128, 127)
    return q.astype(np.int8), s.reshape(-1), zp.reshape(-1)


def grab(path, off, L):
    d, _ = vectors(path)
    return np.frombuffer(d, dtype=np.uint8, count=L, offset=off)


def overlap(a, b):
    ha = np.bincount(np.asarray(a, np.uint8).astype(np.int64), minlength=256)
    hb = np.bincount(np.asarray(b, np.uint8).astype(np.int64), minlength=256)
    return np.minimum(ha, hb).sum() / len(a)


def main():
    b, wdw, wrg = known()

    print("=== control: is the 9216 byte vector plain OIHW? ===")
    v = grab("geom/sv_rgu_rk3576.rknn", 0x0091c0, 9216).view(np.int8)
    q, s, zp = asym_perchannel(wrg.reshape(32, -1))
    same = int((q.reshape(-1) == v).sum())
    print(f"  element for element in OIHW: {same}/9216 "
          f"({100.0*same/9216:.2f}%)")
    if same != 9216:
        # If not, is it a per-channel permutation or a global one?
        perch = [int((q[c] == v.reshape(32, -1)[c]).sum()) for c in range(32)]
        print(f"  per-channel exact counts, first 8: {perch[:8]} of 288")
    print(f"  channel 0: scale {s[0]:.8f} zero point {zp[0]:+.0f}")

    print("\n=== depthwise: what reproduces the 576 byte vector? ===")
    d576 = grab("geom/sv_dwu_rk3576.rknn", 0x009240, 576)
    flat = wdw.reshape(32, 9)

    cands = {}
    q1, _, _ = asym_perchannel(flat)
    cands["per-channel asym, 32 x 9"] = q1.reshape(-1)
    q2, _, _ = asym_perchannel(flat.reshape(1, -1))
    cands["per-tensor asym"] = q2.reshape(-1)
    # A depthwise weight is sometimes carried as (1, 32, 3, 3), which makes the
    # single output channel the quantisation group but keeps 32 planes.
    q3, _, _ = asym_perchannel(flat.T.reshape(9, 32))
    cands["asym per tap position"] = q3.reshape(-1)

    for name, q in cands.items():
        u = np.asarray(q, np.int8).view(np.uint8)
        best = max((overlap(d576[o:o + 288], u), o)
                   for o in range(0, 576 - 288 + 1))
        print(f"  {name}: best {best[0]*100:.2f}% at +{best[1]}")
        exact = int((np.asarray(q, np.int8) == d576.view(np.int8)[:288]).sum())
        print(f"    element for element at +0: {exact}/288")

    print("\n  is the 576 two interleaved 288s, or 288 int16?")
    i8 = d576.view(np.int8)
    ev, od = i8[0::2], i8[1::2]
    for name, half in (("even bytes", ev), ("odd bytes", od),
                       ("first half", i8[:288]), ("second half", i8[288:])):
        sc = max(overlap(np.asarray(half, np.uint8),
                         np.asarray(q, np.int8).view(np.uint8))
                 for q in cands.values())
        print(f"    {name}: best multiset overlap with any candidate "
              f"{sc*100:.2f}%")


if __name__ == "__main__":
    main()
