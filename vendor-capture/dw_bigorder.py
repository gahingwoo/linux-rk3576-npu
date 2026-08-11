#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
At 1024 channels, is the vendor's depthwise weight buffer still tap major?

Round 68 measured the fault: with one live tap in every channel, the channels
that produce anything are a contiguous run that moves with the tap, and
inverting the nine runs shows each output channel can reach only ONE OR TWO of
its nine spatial blocks. A depthwise needs all nine.

mesa writes tap major with a block stride of 2C bytes, 64 at 32 channels and
2048 at 1024. The 32 channel layout is not a guess: it reproduces the vendor's
own 576 bytes, 288 of 288 weight lanes. And the vendor's 1024 channel buffer is
18432 bytes, exactly the size mesa writes, so the SIZE is right and only the
ORDER can differ.

Both candidate orders hold 18 bytes per channel. They differ in which of the
two indices strides fastest:

    tap major     buf[p * DIV_ROUND_UP(C,2)*4 + (c//2)*4 + c%2]     mesa
    channel major buf[(c//2)*36 + p*4 + c%2]                        18 per channel

The weights are generated here, so this is an exact test, and the 32 channel
model is the control: tap major has to win there or the reader is wrong.
"""
import os
import sys

import numpy as np

from rknn_blobs import vectors


def known(channels, k=3):
    rng = np.random.RandomState(11)
    w = (rng.randn(channels, 1, k, k) * 0.08).astype(np.float32)
    return w.reshape(channels, k * k)


def asym_perchannel(flat):
    lo = flat.min(axis=1, keepdims=True)
    hi = flat.max(axis=1, keepdims=True)
    s = (hi - lo) / 255.0
    zp = np.rint(-lo / s) - 128
    return np.clip(np.rint(flat / s) + zp, -128, 127).astype(np.int8), \
        s.reshape(-1), zp.reshape(-1)


def grab(path, want_len):
    d, vs = vectors(path)
    for off, L, _ in vs:
        if L == want_len:
            return np.frombuffer(d, dtype=np.uint8, count=L,
                                 offset=off).view(np.int8), off
    return None, None


def score(buf, q, zp, C, k=3):
    """How many of the C*k*k weight lanes each candidate order explains."""
    taps = k * k
    block = ((C + 1) // 2) * 4
    out = {}

    hits = 0
    for p in range(taps):
        for c in range(C):
            idx = p * block + (c // 2) * 4 + (c % 2)
            if idx < len(buf) and buf[idx] == q[c, p]:
                hits += 1
    out["tap major, block = ceil(C/2)*4 (mesa)"] = hits

    hits = 0
    for p in range(taps):
        for c in range(C):
            idx = (c // 2) * (taps * 4) + p * 4 + (c % 2)
            if idx < len(buf) and buf[idx] == q[c, p]:
                hits += 1
    out["channel major, 36 bytes per channel pair"] = hits

    hits = 0
    for p in range(taps):
        for c in range(C):
            idx = c * 18 + p * 2
            if idx < len(buf) and buf[idx] == q[c, p]:
                hits += 1
    out["channel major, 18 bytes per channel"] = hits

    # The zero point lanes say where the pad bytes went, which the 32 channel
    # capture showed to be the negated per-channel weight zero point.
    zhits = 0
    for p in range(taps):
        for g in range((C + 1) // 2):
            for s in range(2):
                c = g * 2 + s
                if c >= C:
                    continue
                idx = p * block + g * 4 + 2 + s
                if idx < len(buf) and buf[idx] == -int(zp[c]):
                    zhits += 1
    out["  (tap major zero point lanes)"] = zhits
    return out


def main():
    for ch in (32, 128, 256, 1024):
        path = f"geom/dwbig_{ch}_rk3576.rknn"
        if not os.path.exists(path):
            print(f"\n=== {ch} channels: no model, skipped ===")
            continue
        w = known(ch)
        q, sc, zp = asym_perchannel(w)
        want = 9 * ((ch + 1) // 2) * 4
        buf, off = grab(path, want)
        print(f"\n=== {ch} channels: {want} byte vector "
              f"{'at 0x%06x' % off if off is not None else 'NOT FOUND'} ===")
        if buf is None:
            continue
        total = ch * 9
        for name, hits in score(buf, q, zp, ch).items():
            print(f"  {name:44s} {hits:6d} / {total}"
                  f"{'   EXACT' if hits == total else ''}")


if __name__ == "__main__":
    main()
