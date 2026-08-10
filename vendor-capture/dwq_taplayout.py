#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Test one specific reading of the 576 byte depthwise weight vector.

The register diff between sv_dwu and sv_rgu, which differ only in `groups`,
puts 0x2400 in CNA 0x101c for the regular conv and 0x0240 for the depthwise
one. 0x2400 is 9216, which is exactly the regular conv's weight count, and
0x0240 is 576, which is exactly the length of the depthwise weight vector in
the .rknn. So 576 is the hardware's own idea of how many weight bytes a
depthwise layer of this shape has, for a tensor with 288 elements in it.

576 = 9 taps x 64 bytes. A depthwise layer runs all its channels through the
same tap at once, so a per-tap plane of 32 channels padded up to a 64 byte
line is the layout the hardware would want, and it is the one thing that
explains the factor of two without invoking int16.

DECISION RULE, written before the run:
  padding is zero and the 32 live bytes per plane are the per-channel int8
      -> the layout is [tap][channel], and mesa's depthwise packing is wrong
  the live bytes match under a different plane size (32, 128)
      -> same idea, different line
  no arrangement matches
      -> the vector is not plain int8 and the factor of two is something else

The control is the regular conv: the same code path is run on its 9216 byte
vector, where the answer is already known to be a shuffle of the right values,
so a bug that makes everything match would show up there as a false hit.
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
    return np.clip(np.rint(flat / s) + zp, -128, 127).astype(np.int8), \
        s.reshape(-1), zp.reshape(-1)


def grab(path, off, L):
    d, _ = vectors(path)
    return np.frombuffer(d, dtype=np.uint8, count=L, offset=off)


def main():
    b, wdw, wrg = known()
    q, s, zp = asym_perchannel(wdw.reshape(32, 9))
    v = grab("geom/sv_dwu_rk3576.rknn", 0x009240, 576)
    i8 = v.view(np.int8)

    print("=== 576 bytes as [tap][channel] planes ===")
    for line in (32, 64, 128, 192):
        if 9 * line > 576 and line != 64:
            pass
        n_planes = 576 // line
        print(f"\n  line {line} bytes, {n_planes} planes:")
        if n_planes < 9:
            print("    fewer than 9 planes, cannot hold 9 taps")
            continue
        planes = i8[:n_planes * line].reshape(n_planes, line)
        live = planes[:9, :32]
        exact = int((live == q.T[:9]).sum())
        print(f"    live 9x32 vs q[channel][tap] transposed: {exact}/288 exact")
        if line > 32:
            pad = planes[:9, 32:]
            print(f"    padding bytes nonzero: {int((pad != 0).sum())}/"
                  f"{pad.size}")

    print("\n=== the same 576 read as [channel][tap] with a stride ===")
    for stride in (9, 16, 18, 32):
        if 32 * stride > 576:
            print(f"  stride {stride}: does not fit")
            continue
        idx = (np.arange(32)[:, None] * stride + np.arange(9)[None, :])
        cand = i8[idx]
        exact = int((cand == q).sum())
        print(f"  stride {stride}: {exact}/288 exact")

    print("\n=== control: the regular conv's 9216, same treatment ===")
    qr, _, _ = asym_perchannel(wrg.reshape(32, -1))
    vr = grab("geom/sv_rgu_rk3576.rknn", 0x0091c0, 9216).view(np.int8)
    print(f"  plain OIHW: {int((vr == qr.reshape(-1)).sum())}/9216")
    pl = vr.reshape(32, 288)
    print(f"  as 32 planes of 288: {int((pl == qr).sum())}/9216")
    # [ic][oc][k][k] rather than [oc][ic][k][k]
    t = qr.reshape(32, 32, 9).transpose(1, 0, 2).reshape(-1)
    print(f"  transposed to [ic][oc][tap]: {int((vr == t).sum())}/9216")
    # [oc][tap][ic]
    t2 = qr.reshape(32, 32, 9).transpose(0, 2, 1).reshape(-1)
    print(f"  as [oc][tap][ic]: {int((vr == t2).sum())}/9216")


if __name__ == "__main__":
    main()
