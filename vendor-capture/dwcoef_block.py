#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Read the coefficient region as BLOCKS of eight channels, which is the layout
this project already derived for regular convolutions:

    A   8 x int32 at +0
    B   8 x int16 at +32
    C   8 x int16 at +48        64 bytes per group of eight channels

The control is the regular conv in the same capture, where that layout is
already known to be right, so if it does not read back as A, B and C here the
reader is wrong and the depthwise reading beside it means nothing.

B is the one term that can be checked without knowing the input scale: for a
regular conv B is the negated weight zero point, and the toolkit's per-channel
zero points are computable here from the known weights. That gives the control
a pass/fail that does not depend on any fitted constant.

The depthwise region is 448 bytes for 32 channels against the regular's 320.
Both end with the same four byte operand pointer, so if the last 64 bytes are
the fp16 per-channel scale table in both, the tables in front are 256 and 384
bytes, that is 64 and 96 bytes per group of eight.
"""
import os
import sys

import numpy as np


def bo(path, idx):
    return np.frombuffer(open(os.path.join(path, f"bo{idx:02d}.bin"), "rb").read(),
                         dtype=np.uint8)


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
    return np.clip(np.rint(flat / s) + zp, -128, 127).astype(np.int8), \
        s.reshape(-1), zp.reshape(-1)


def half(v):
    return np.frombuffer(v.tobytes(), dtype="<f2")


def read_blocks(v, block, tag, zp, sc, bias, sw):
    n = len(v) // block
    print(f"\n  as {n} blocks of {block} bytes:")
    A = []
    for g in range(n):
        blk = v[g * block:(g + 1) * block]
        A.append(blk[:32].view("<i4"))
        i16 = blk[32:].view("<i2")
        if g == 0:
            print(f"    block 0 int32[0:8]  {[int(x) for x in blk[:32].view('<i4')]}")
            print(f"    block 0 rest int16  {[int(x) for x in i16]}")
    A = np.concatenate(A)[:32].astype(np.float64)
    print(f"    A column: {[int(x) for x in A[:6]]} ...")
    # B, at +32 as int16, against the negated per-channel weight zero point
    B = np.concatenate([v[g * block + 32:g * block + 48].view("<i2")
                        for g in range(n)])[:32].astype(np.float64)
    print(f"    +32 int16 column: {[int(x) for x in B[:8]]}")
    print(f"    negated weight zero point: {[int(-x) for x in zp[:8]]}")
    print(f"    match: {int((B == -zp).sum())}/32")
    C = np.concatenate([v[g * block + 48:g * block + 64].view("<i2")
                        for g in range(n)])[:32].astype(np.float64)
    print(f"    +48 int16 column: {[int(x) for x in C[:8]]}")
    for name, ref in (("bias/wt_sc", bias / sc), ("bias", bias),
                      ("weight sum", sw), ("bias/wt_sc - 128*sw",
                                           bias / sc - 128 * sw)):
        c = np.corrcoef(A, ref)[0, 1]
        print(f"    A vs {name:22s} corr {c:+.6f}")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    b, wdw, wrg = known()

    for tag, base, length, w, block in (
            ("sv_rgu", 0x2400, 320, wrg, 64),
            ("sv_dwu", 0x0240, 448, wdw, 96)):
        raw = bo(os.path.join(root, tag), 1)
        q, sc, zp = asym_perchannel(w.reshape(32, -1))
        sw = q.astype(np.float64).sum(axis=1)
        v = raw[base:base + length]
        print(f"\n=== {tag}: {length} bytes at 0x{base:05x} ===")
        tail = v[-64:]
        print(f"  last 64 bytes as fp16: "
              f"{[round(float(x), 5) for x in half(tail)[:8]]} ...")
        c = np.corrcoef(half(tail).astype(np.float64), sc)[0, 1]
        print(f"  last 64 bytes as 32 fp16 vs weight scale: corr {c:+.6f}"
              f"   ratio {(half(tail).astype(np.float64) / sc).mean():.5f}")
        read_blocks(v[:length - 64], block, tag, zp, sc, b.astype(np.float64), sw)


if __name__ == "__main__":
    main()
