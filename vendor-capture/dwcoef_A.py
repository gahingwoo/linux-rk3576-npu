#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Check that depthwise A is the same A the regular conv uses.

The structure is settled: the depthwise coefficient table is 48 byte records,
[A 8 x int32][C 8 x int16], one record per eight channels, in channel order,
and C read back exactly as 0x4000 * scale_c / max(scale) for all 32 channels.
A is the only term left.

For a regular conv this project derived

    A = bias / (in_scale * wt_scale_c) - (in_zp - 0x80) * sum(q_weights_c)

Both models here were calibrated with the same generated set, values 0 to 250,
so in_scale and in_zp are not free parameters: 250/255 and -128 in the int8
domain. That makes A a PREDICTION with nothing fitted, and the regular conv in
the same capture is the control that says whether the prediction is right
before the depthwise number is read.

DECISION RULE, written before the run:
  control A predicted exactly, depthwise A predicted exactly
      -> the depthwise table is fully derived and mesa can write it
  control exact, depthwise not
      -> A is different for depthwise, and the residual says how
  control not exact
      -> the input quantisation assumed here is wrong, and nothing else in
         this file can be read
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


def columns(raw, base, table_len, rec, a_len=32):
    v = raw[base:base + table_len]
    n = table_len // rec
    A = np.concatenate([v[r * rec:r * rec + a_len].view("<i4") for r in range(n)])
    return A.astype(np.float64)


def check(tag, root, base, table_len, rec, w, bias):
    raw = bo(os.path.join(root, tag), 1)
    q, sc, zp = asym_perchannel(w.reshape(32, -1))
    sw = q.astype(np.float64).sum(axis=1)
    A = columns(raw, base, table_len, rec)[:32]

    in_sc = 250.0 / 255.0
    n_taps = w[0].size
    print(f"\n=== {tag} ===  {n_taps} taps per output channel")
    for in_zp in (-128.0, 0.0, 128.0):
        pred = np.rint(bias / (in_sc * sc) - in_zp * sw)
        exact = int((pred == A).sum())
        err = np.abs(pred - A)
        print(f"  bias_q - in_zp*sum(q), in_zp {in_zp:+7.1f}: {exact}/32 exact, "
              f"max error {err.max():.1f}")

    # The weights are quantised ASYMMETRICALLY per channel here, so the MAC's
    # expansion carries a constant term the symmetric formula never had:
    #   sum (x - x_zp)(w - w_zp) = sum x.w - x_zp.sum w - w_zp.sum x
    #                              + N.x_zp.w_zp
    # Everything input dependent is the hardware's job; what is left for A is
    # the bias plus x_zp * (N * w_zp - sum w).
    for in_zp in (-128.0, 128.0):
        pred = np.rint(bias / (in_sc * sc)) + in_zp * (n_taps * zp - sw)
        exact = int((pred == A).sum())
        err = np.abs(pred - A)
        print(f"  bias_q + in_zp*(N*w_zp - sum(q)), in_zp {in_zp:+7.1f}: "
              f"{exact}/32 exact, max error {err.max():.1f}")

    # If nothing is exact, fit the two coefficients and look at the residual:
    # A = u * bias/scale_c + v * sw.
    M = np.stack([bias / sc, sw], axis=1)
    coef, *_ = np.linalg.lstsq(M, A, rcond=None)
    res = A - M @ coef
    print(f"  least squares fit: bias/scale_c x {coef[0]:.6f} + "
          f"sum(q) x {coef[1]:.6f}   max residual {np.abs(res).max():.2f}")
    print(f"    1/that first coefficient = {1.0/coef[0]:.6f} "
          f"(in_scale would be {in_sc:.6f})")
    print(f"  A[0:4] {[int(x) for x in A[:4]]}   "
          f"bias/scale_c[0:4] {[round(float(x), 1) for x in (bias/sc)[:4]]}   "
          f"sum(q)[0:4] {[int(x) for x in sw[:4]]}")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    b, wdw, wrg = known()
    bias = b.astype(np.float64)
    check("sv_rgu", root, 0x2400, 256, 64, wrg, bias)
    check("sv_dwu", root, 0x0240, 384, 48, wdw, bias)


if __name__ == "__main__":
    main()
