#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Read the two weight vectors the previous step found, and say what is in them.

  sv_rgu   a 9216 byte vector at 0x0091c0, which is exactly 32 x 32 x 3 x 3.
  sv_dwu   a 576 byte vector at 0x009240, which is exactly TWICE 32 x 1 x 3 x 3.

Both scored well under 100 percent against the int8 computed here, so the first
job is to pin the toolkit's own rounding by fitting the regular one, where the
element count matches the tensor exactly and no layout question is in the way.
Once the regular vector is explained element for element, the same rule is
applied to the depthwise one, and the factor of two is the thing to explain.

⚠ 576 is also 32 channels x 18 bytes, and 18 is 9 taps of int16. That is a
hypothesis, not a reading: it is tested below against the known values, and
the int8 reading is tested alongside it so the comparison can fail.
"""
import numpy as np

from rknn_blobs import vectors


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    wrg = (rng.randn(32, 32, 3, 3) * 0.08).astype(np.float32)
    return b, wdw, wrg


def grab(path, off, L):
    d, _ = vectors(path)
    return np.frombuffer(d, dtype=np.uint8, count=L, offset=off)


def fit_int8(raw_i8, w, order):
    """Match a candidate ordering of w against the stored int8, per channel."""
    q = raw_i8.astype(np.float64)
    oc = w.shape[0]
    flat = w.transpose(order).reshape(oc, -1) if order else w.reshape(oc, -1)
    n = flat.shape[1]
    ok = 0
    scales = []
    for c in range(oc):
        seg = q[c * n:(c + 1) * n]
        f = flat[c]
        denom = (seg * seg).sum()
        s = (seg * f).sum() / denom if denom else 0.0
        pred = np.clip(np.rint(f / s), -128, 127) if s else np.zeros(n)
        ok += int((pred == seg).sum())
        scales.append(s)
    return ok / (oc * n), np.array(scales)


def main():
    b, wdw, wrg = known()

    print("=== sv_rgu, 9216 bytes: is it plain per-channel int8 in OIHW? ===")
    v = grab("geom/sv_rgu_rk3576.rknn", 0x0091c0, 9216).view(np.int8)
    frac, sc = fit_int8(v, wrg, None)
    print(f"  OIHW, per-channel scale fitted from the data: "
          f"{frac*100:.2f}% of 9216 elements match")
    print(f"  fitted scale ch0 {sc[0]:.8f}   max|w0|/127 "
          f"{np.abs(wrg[0]).max()/127:.8f}")
    for order in ((0, 2, 3, 1), (0, 1, 3, 2)):
        f2, _ = fit_int8(v, wrg, order)
        print(f"  transpose {order}: {f2*100:.2f}%")

    print("\n=== sv_dwu, 576 bytes: what are the 576 bytes? ===")
    d = grab("geom/sv_dwu_rk3576.rknn", 0x009240, 576)
    i8 = d.view(np.int8)
    i16 = d.view("<i2")
    print(f"  as int8:  min {i8.min()} max {i8.max()}  zeros {int((i8==0).sum())}")
    print(f"  as int16: min {i16.min()} max {i16.max()}  zeros {int((i16==0).sum())}")
    print(f"  first 32 bytes: {' '.join(f'{x:02x}' for x in d[:32])}")
    print(f"  bytes 288..320: {' '.join(f'{x:02x}' for x in d[288:320])}")
    halves_equal = np.array_equal(d[:288], d[288:])
    print(f"  second half identical to first: {halves_equal}")

    flat = wdw.reshape(32, 9)
    for name, cand in (("first 288 as int8", i8[:288]),
                       ("second 288 as int8", i8[288:]),
                       ("288 int16", i16)):
        c = np.asarray(cand, dtype=np.float64)
        if len(c) != 288:
            continue
        ok = 0
        for ch in range(32):
            seg = c[ch * 9:(ch + 1) * 9]
            f = flat[ch]
            den = (seg * seg).sum()
            s = (seg * f).sum() / den if den else 0.0
            pred = np.rint(f / s) if s else np.zeros(9)
            ok += int((pred == seg).sum())
        print(f"  {name}: {ok}/288 elements match a per-channel scale fit")

    # Correlation is weaker than an exact fit but survives a reordering inside
    # the channel, so it separates "wrong values" from "right values, shuffled".
    for name, cand in (("first 288 int8", i8[:288].astype(float)),
                       ("second 288 int8", i8[288:].astype(float)),
                       ("288 int16", i16.astype(float))):
        cs = []
        for ch in range(32):
            seg = np.sort(cand[ch * 9:(ch + 1) * 9])
            f = np.sort(flat[ch])
            cs.append(np.corrcoef(seg, f)[0, 1])
        cs = np.nan_to_num(cs)
        print(f"  {name}: sorted-within-channel corr mean {cs.mean():+.4f} "
              f"min {cs.min():+.4f}")


if __name__ == "__main__":
    main()
