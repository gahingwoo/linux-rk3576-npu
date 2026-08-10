#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Read the depthwise per-channel coefficient table, which does exist.

Every earlier search for it was run against the .rknn, and it is not in the
.rknn: librknnrt builds it at load time. The capture shows it plainly. For
sv_dwu the address registers resolve to

    CNA  0x1110 -> bo1+0x0000   the 576 byte weight buffer, already decoded
    RDMA 0x5020 -> bo1+0x0240   immediately after it
    RDMA 0x5024 -> bo1+0x0400   the four byte operand, 0x0E0E

so the per-channel region is bo1+0x0240..0x0400, 448 bytes, for 32 channels.
The regular conv in the same capture has the same shape of thing: 0x5020 at
bo1+0x2400 right after its 9216 byte weight buffer and 0x5024 320 bytes later,
and 320 is exactly the 256 byte A/B/C table plus 64 bytes of fp16 per-channel
scale that this project already derived. 448 is 384 plus the same 64.

So the question is what the 384 bytes are, and the regular conv's 256 is the
control: the same code decodes it, and it must come out as the known A, B and C
or the decoding is wrong.
"""
import os
import re
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


def dump(raw, base, length, label, per):
    v = raw[base:base + length]
    print(f"\n  {label}: {length} bytes at 0x{base:05x}, {per} bytes per channel")
    i32 = v.view("<i4")
    i16 = v.view("<i2")
    f32 = v.view("<f4")
    print(f"    int32[0:8]  {[int(x) for x in i32[:8]]}")
    print(f"    int16[0:16] {[int(x) for x in i16[:16]]}")
    print(f"    fp32[0:6]   {[round(float(x), 6) for x in f32[:6]]}")
    print(f"    first 32 bytes: {' '.join(f'{x:02x}' for x in v[:32])}")


def correlate(raw, base, length, refs, per_candidates=(4, 8, 12, 16, 48, 64, 96)):
    """Score every per-channel column in the region against known quantities."""
    v = raw[base:base + length]
    out = []
    for dt, esz in (("<i4", 4), ("<i2", 2), ("<f4", 4)):
        for stride in per_candidates:
            if stride * 32 > length or stride % esz:
                continue
            for off in range(0, stride, esz):
                idx = off + np.arange(32) * stride
                if idx[-1] + esz > length:
                    continue
                col = np.array([v[i:i + esz].view(dt)[0] for i in idx],
                               dtype=np.float64)
                if not np.isfinite(col).all() or col.std() == 0:
                    continue
                for rn, rv in refs.items():
                    c = np.corrcoef(col, rv)[0, 1]
                    if abs(c) > 0.995:
                        out.append((abs(c), dt, stride, off, rn, c, col))
    out.sort(key=lambda r: -r[0])
    seen = set()
    for a, dt, stride, off, rn, c, col in out:
        if (dt, stride, off) in seen:
            continue
        seen.add((dt, stride, off))
        ratio = col / refs[rn]
        print(f"    {dt} stride {stride:3d} offset {off:3d}  vs {rn:24s} "
              f"corr {c:+.6f}  ratio {ratio.mean():.5f} +- {ratio.std():.5f}")
        if len(seen) >= 12:
            break
    if not seen:
        print("    nothing above 0.995")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    b, wdw, wrg = known()

    for tag, base, length, w in (("sv_rgu (control, regular)", 0x2400, 320, wrg),
                                 ("sv_dwu (depthwise)", 0x0240, 448, wdw)):
        path = os.path.join(root, tag.split()[0])
        raw = bo(path, 1)
        q, sc, zp = asym_perchannel(w.reshape(32, -1))
        sw = q.astype(np.float64).sum(axis=1)
        refs = {
            "bias": b.astype(np.float64),
            "weight sum q": sw,
            "weight scale": sc,
            "1/weight scale": 1.0 / sc,
            "weight zero point": zp,
            "bias / weight scale": b / sc,
            "sw / weight scale": sw / sc,
            "bias - 0*sw": b.astype(np.float64),
        }
        for k in (1.0, -1.0, 128.0, -128.0):
            refs[f"bias/wsc {k:+.0f}*sw"] = b / sc + k * sw
        print(f"\n=== {tag} ===")
        dump(raw, base, length, "coefficient region", length // 32)
        print("  per-channel columns:")
        correlate(raw, base, length, refs)


if __name__ == "__main__":
    main()
