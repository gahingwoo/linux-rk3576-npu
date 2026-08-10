#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Check the depthwise weight layout mesa ALREADY writes against the vendor's own
576 bytes for the same shape.

rkt_coefs.c has carried an RK3576 depthwise packing since the first-conv work:
nine spatial blocks, each 64 bytes, channels in pairs followed by two
weight-zero-point pad bytes,

    buf[p*64 + g*4 + 0] = w[2g  ][ky][kx]
    buf[p*64 + g*4 + 1] = w[2g+1][ky][kx]
    buf[p*64 + g*4 + 2] = zp
    buf[p*64 + g*4 + 3] = zp

and it was arrived at from a position-encoded capture. sv_dwu gives the first
chance to check it against a vendor buffer for a layer whose weights are known
here exactly, which is a different and stronger test than a position code:
a position code confirms WHERE each byte goes, this confirms that nothing else
is in the buffer.

The plane order is the other half of the question. p = ky*KW + kx is what mesa
writes; the transpose is tried alongside so the test can distinguish them.

DECISION RULE, written before the run:
  288/288 under one plane order   mesa's depthwise weight layout is correct and
                                  the depthwise bug is NOT the weight buffer
  288/288 under the transpose     mesa has ky and kx swapped, a one line fix
  neither                         the layout is wrong, and the pad lanes say
                                  how
"""
import numpy as np

from rknn_blobs import vectors


def known():
    rng = np.random.RandomState(7)
    b = (rng.randn(32) * 0.05).astype(np.float32)
    wdw = (rng.randn(32, 1, 3, 3) * 0.08).astype(np.float32)
    return b, wdw


def asym_perchannel(flat):
    lo = flat.min(axis=1, keepdims=True)
    hi = flat.max(axis=1, keepdims=True)
    s = (hi - lo) / 255.0
    zp = np.rint(-lo / s) - 128
    return np.clip(np.rint(flat / s) + zp, -128, 127).astype(np.int8), \
        s.reshape(-1), zp.reshape(-1)


def main():
    b, wdw = known()
    q, s, zp = asym_perchannel(wdw.reshape(32, 9))   # q[channel][tap]
    q = q.reshape(32, 3, 3)                          # [channel][ky][kx]

    d, _ = vectors("geom/sv_dwu_rk3576.rknn")
    v = np.frombuffer(d, dtype=np.uint8, count=576, offset=0x009240).view(np.int8)
    blocks = v.reshape(9, 64)

    for name, order in (("ky major (mesa)", lambda ky, kx: ky * 3 + kx),
                        ("kx major", lambda ky, kx: kx * 3 + ky)):
        hits = 0
        for ky in range(3):
            for kx in range(3):
                p = order(ky, kx)
                blk = blocks[p]
                for g in range(16):
                    for sIdx in range(2):
                        c = g * 2 + sIdx
                        if blk[g * 4 + sIdx] == q[c, ky, kx]:
                            hits += 1
        print(f"  {name}: {hits}/288 weight lanes match")

    lanes = blocks.reshape(9, 16, 4)
    pads = lanes[:, :, 2:].reshape(-1)
    print(f"\n  pad lanes (+2, +3 of each 4): {len(pads)} bytes, "
          f"{len(np.unique(pads))} distinct, values "
          f"{sorted(set(int(x) for x in pads))[:8]}")
    print(f"  weight lanes (+0, +1): "
          f"{len(np.unique(lanes[:, :, :2]))} distinct")
    u = blocks.view(np.uint8)
    print(f"\n  block 0, first 16 bytes: "
          f"{' '.join(f'{x:02x}' for x in u[0][:16])}")
    print(f"  block 1, first 16 bytes: "
          f"{' '.join(f'{x:02x}' for x in u[1][:16])}")

    print(f"\n  per-channel zero points, first 8: "
          f"{[int(x) for x in zp[:8]]}")
    print(f"  per-channel scales, first 4: {[float(x) for x in s[:4]]}")

    # Are the two pad bytes of a channel pair that pair's weight ZERO POINTS?
    # For a regular conv the zero point compensation is B in the A/B/C table,
    # and the vendor emits no such table for depthwise, so it has to be
    # somewhere and this is the only per-channel room left in the buffer.
    ok = 0
    for p in range(9):
        for g in range(16):
            if lanes[p, g, 2] == zp[2 * g]:
                ok += 1
            if lanes[p, g, 3] == zp[2 * g + 1]:
                ok += 1
    print(f"\n  pad lanes vs per-channel weight zero point: {ok}/288")
    print(f"  pad bytes of block 0, per pair: "
          f"{[(int(lanes[0, g, 2]), int(lanes[0, g, 3])) for g in range(4)]}")
    print(f"  zp of channels 0..7: {[int(x) for x in zp[:8]]}")
    same_all_planes = all(
        np.array_equal(lanes[0, :, 2:], lanes[p, :, 2:]) for p in range(9))
    print(f"  pad lanes identical in every spatial block: {same_all_planes}")


if __name__ == "__main__":
    main()
