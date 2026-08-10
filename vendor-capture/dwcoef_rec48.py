#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Pin the depthwise record and the channel it belongs to.

Reading the depthwise region as 96 byte groups showed the structure straight
away: 32 bytes of int32, 16 bytes of int16 in the 0x4000 range, then the same
pair again. That is two records of 48 bytes, [A 8 x int32][C 8 x int16], with
no B, which is the record mesa already implements behind ROCKET_DW_REC48. The
region holds 384 bytes of it, eight records, for a layer with 32 channels, so
the question that is left is which record slot belongs to which channel.

C answers that without any fitted constant. For a regular conv C is
0x4000 * scale_c / max(scale), the per-channel weight scale renormalised, and
the weight scales are computable here from the known weights. So the expected
C column is known for all 32 channels, and every record slot can be matched
against it.

The control is the regular conv in the same capture, whose C column reads back
correctly under the 64 byte record. It is scored the same way here.

DECISION RULE, written before the run:
  every channel found exactly once   the mapping is settled and A can be
                                     attacked next
  each channel found twice           the table is duplicated, and that is the
                                     thing mesa is not doing
  no match                           C is not the weight scale for depthwise
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


def show(tag, root, base, table_len, rec, w, c_off, c_len):
    raw = bo(os.path.join(root, tag), 1)
    q, sc, zp = asym_perchannel(w.reshape(32, -1))
    want = np.rint(16384.0 * sc / sc.max()).astype(int)
    v = raw[base:base + table_len]
    n = table_len // rec
    print(f"\n=== {tag}: {table_len} bytes, {n} records of {rec} ===")
    print(f"  expected C, channels 0..7: {list(want[:8])}")
    for r in range(n):
        blk = v[r * rec:(r + 1) * rec]
        A = blk[:32].view("<i4")
        C = blk[c_off:c_off + c_len].view("<i2").astype(int)
        # which run of eight channels does this C column match?
        best, bc = -1, None
        for c0 in range(0, 33 - 8):
            m = int((np.abs(C - want[c0:c0 + 8]) <= 1).sum())
            if m > best:
                best, bc = m, c0
        print(f"  record {r}: C {list(C)}")
        print(f"            best match channels {bc}..{bc+7}: {best}/8 within 1"
              f"   A {[int(x) for x in A[:4]]} ...")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    b, wdw, wrg = known()
    show("sv_rgu", root, 0x2400, 256, 64, wrg, 48, 16)
    show("sv_dwu", root, 0x0240, 384, 48, wdw, 32, 16)


if __name__ == "__main__":
    main()
