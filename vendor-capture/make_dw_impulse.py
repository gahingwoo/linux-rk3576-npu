#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
A depthwise conv whose CORRECT OUTPUT NAMES THE LAYOUT, built by patching
mn_dw1.tflite's weight and bias bytes in place.

The coefficient surface is exonerated. Rounds 57 and 58 swept the OUT_CVT
shift, A alone from 2^-7 to 2^7, and C on the depthwise path, and COMPUTED
never left 1 on mn_dw1 or 2 on mn_dw25, while the same knobs visibly break or
move a regular conv. Everything in the record is verified against the vendor
capture anyway. The depthwise conv fires on every channel and computes the
wrong number, and no scalar this driver writes changes which number.

So the suspect is which INPUT each multiply gets, and a random model cannot see
that: every wrong answer looks like a wrong answer. An impulse can.

Every tap is set to the weight zero point, which is exactly zero after
dequantisation, except ONE tap per channel at position c mod 9. The bias is
zeroed. mn_dw1's input and output scales are equal, so with an effective weight
near 1 the correct output of channel c IS its input, shifted by that tap:

  right shift, right channel    tap map and channel map are both right
  right shift, wrong channel    the channels are permuted, which is the live
                                suspicion: the weight buffer packs them in
                                PAIRS and CNA 0x1024 carries 1 rather than 31
  wrong shift, right channel    ky and kx are transposed, or the plane order is
  several taps blended          more than one tap lands on a channel, so the 4
                                byte group is being read as 4 weights instead
                                of 2 weights and 2 zero points

Nine tap positions over 32 channels exercises every position three times, so
one run separates all four.

⚠ Patching bytes rather than rebuilding with the converter, because there is no
tensorflow in this environment. Everything structural is inherited from a model
that already runs: shape, quantisation, operator, buffers. Only the contents of
the weight and bias buffers change, and the CPU reference is computed from the
same patched file, so the comparison stays exact.
"""
import os
import struct
import sys

import numpy as np


class T:
    def __init__(self, buf, pos):
        self.b, self.pos = buf, pos
        self.vt = pos - struct.unpack_from("<i", buf, pos)[0]

    def off(self, field):
        if 4 + field * 2 >= struct.unpack_from("<H", self.b, self.vt)[0]:
            return 0
        return struct.unpack_from("<H", self.b, self.vt + 4 + field * 2)[0]

    def sub(self, field):
        o = self.off(field)
        if not o:
            return None
        p = self.pos + o
        return T(self.b, p + struct.unpack_from("<I", self.b, p)[0])

    def vec(self, field, fmt):
        o = self.off(field)
        if not o:
            return []
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return list(struct.unpack_from(f"<{n}{fmt}", self.b, p + 4))

    def tables(self, field):
        o = self.off(field)
        if not o:
            return []
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return [T(self.b, q + struct.unpack_from("<I", self.b, q)[0])
                for q in (p + 4 + i * 4 for i in range(n))]

    def u32(self, field, default=0):
        o = self.off(field)
        return struct.unpack_from("<I", self.b, self.pos + o)[0] if o else default

    def data_span(self, field):
        """(offset, length) of a [ubyte] vector's payload inside the file."""
        o = self.off(field)
        if not o:
            return None
        p = self.pos + o
        p += struct.unpack_from("<I", self.b, p)[0]
        n = struct.unpack_from("<I", self.b, p)[0]
        return p + 4, n


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else \
        "../rootfs-overlay/opt/npu-test/mn_dw1.tflite"
    dst = sys.argv[2] if len(sys.argv) > 2 else \
        "../rootfs-overlay/opt/npu-test/dw_imp.tflite"
    # A third argument fixes the live tap for EVERY channel instead of using
    # c mod 9. That is the discriminator for the 1024 channel case: the correct
    # channels there are exactly one residue mod 9 per group of 64, 7 or 8 of
    # 64 each, which is what a fixed tap per group looks like. With every
    # channel carrying the same tap, a fixed tap per group must light up whole
    # groups at once and leave the rest flat, and nothing else does.
    fixed = int(sys.argv[3]) if len(sys.argv) > 3 else None

    b = bytearray(open(src, "rb").read())
    root = T(b, struct.unpack_from("<I", b, 0)[0])
    sub = root.tables(2)[0]
    bufs = root.tables(4)
    tens = sub.tables(0)

    info = []
    for t in tens:
        q = t.sub(4)
        info.append({
            "shape": t.vec(0, "i"),
            "buf": t.u32(2),
            "scale": q.vec(2, "f") if q else [],
            "zp": q.vec(3, "q") if q else [],
        })
    for i, t in enumerate(info):
        print(f"  T{i} shape {t['shape']} buffer {t['buf']} "
              f"scale {t['scale'][:1]} zp {t['zp'][:1]}")

    wt = info[1]
    bias = info[2]
    inp, outp = info[0], info[3]
    kh, kw, C = wt["shape"][1], wt["shape"][2], wt["shape"][3]
    if [kh, kw] != [3, 3]:
        print("  not a 3x3 depthwise, stopping")
        return

    w_zp = int(wt["zp"][0])
    w_sc = float(wt["scale"][0])
    in_sc, out_sc = float(inp["scale"][0]), float(outp["scale"][0])
    # The input and output scales are equal here, so an effective weight of one
    # maps the input straight through. Pick the code that lands nearest to one
    # from BELOW, so nothing saturates.
    step = w_sc / (in_sc / out_sc)
    v = w_zp + int(np.floor(1.0 / step))
    print(f"\n  weight zp {w_zp} scale {w_sc:.8f}, in {in_sc:.8f} "
          f"out {out_sc:.8f}")
    print(f"  impulse code {v}, effective weight "
          f"{(v - w_zp) * w_sc * in_sc / out_sc:.4f}")
    if not 0 <= v <= 255:
        print("  impulse code out of range, stopping")
        return

    woff, wlen = wt_span = bufs[wt["buf"]].data_span(0)
    boff, blen = bufs[bias["buf"]].data_span(0)
    print(f"  weight buffer at 0x{woff:x} length {wlen} (expect {kh*kw*C})")
    print(f"  bias buffer   at 0x{boff:x} length {blen} (expect {4*C})")
    if wlen != kh * kw * C or blen != 4 * C:
        print("  buffer sizes are not what the shapes say, stopping")
        return

    # tflite depthwise weights are [1, ky, kx, C]
    for ky in range(kh):
        for kx in range(kw):
            for c in range(C):
                idx = woff + (ky * kw + kx) * C + c
                on = (fixed if fixed is not None else c % 9) == \
                     (ky * 3 + kx)
                b[idx] = v if on else w_zp
    b[boff:boff + blen] = b"\x00" * blen

    open(dst, "wb").write(bytes(b))
    print(f"\n  wrote {dst}")
    if fixed is None:
        print(f"  tap per channel (ky, kx), first 10: "
              f"{[((c % 9) // 3, (c % 9) % 3) for c in range(10)]}")
    else:
        print(f"  tap FIXED for every channel: {(fixed // 3, fixed % 3)}")
    print("  channel c reads the input at (y - ky + 1, x - kx + 1), so channel "
          "4 is the identity")


if __name__ == "__main__":
    main()
