#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
A first conv whose CORRECT OUTPUT NAMES ITS INPUT LAYOUT, by patching
mn_conv0.tflite's weight and bias bytes in place.

conv0 computes the wrong thing. Its 22 hardcoded registers are identical to the
vendor's for the same geometry, its ARGB weight layout reproduces the vendor's
864 of 864 lanes, and sweeping the requant with the accumulator alive moves the
output everywhere without making one channel COMPUTED, so the accumulator
itself is wrong rather than its scaling.

What has never been checked is the INPUT. A first conv has three channels and
the CNA reads them in four byte groups with an alpha lane, and mesa hands the
tflite tensor over as it is, three bytes per pixel. If the hardware wants four,
every pixel after the first is read from the wrong place.

An impulse says so directly. Output channel c gets a single live tap, at input
channel c mod 3 and tap position (c / 3) mod 9, everything else at the weight
zero point, and a zero bias. The correct output of channel c is then input
plane c mod 3 shifted by that tap, so reading which plane and which shift the
hardware actually produced names the layout:

  right plane, right shift      the input path is fine and the fault is
                                elsewhere in the accumulator
  plane shifted by one          three channels are being read as four, or the
                                other way about
  the plane wanders with c      the pixel stride is wrong, and how fast it
                                wanders gives the stride

Usage: make_fc_impulse.py [src.tflite] [dst.tflite]
"""
import struct
import sys

import numpy as np

from make_dw_impulse import T


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else \
        "../rootfs-overlay/opt/npu-test/mn_conv0.tflite"
    dst = sys.argv[2] if len(sys.argv) > 2 else \
        "../rootfs-overlay/opt/npu-test/fc_imp.tflite"
    # mode: "imp" one live tap per channel and a zero bias, the default;
    #       "all" every tap live, zero bias, so the accumulator sums 27 terms
    #             and any per-tap zero point compensation error shows up;
    #       "bias" one live tap but the model's REAL bias kept.
    #
    # fc_imp is byte exact and mn_conv0 is not, and the two differ in exactly
    # those two things, so this separates them.
    mode = sys.argv[3] if len(sys.argv) > 3 else "imp"

    b = bytearray(open(src, "rb").read())
    root = T(b, struct.unpack_from("<I", b, 0)[0])
    sub = root.tables(2)[0]
    bufs = root.tables(4)

    info = []
    for t in sub.tables(0):
        q = t.sub(4)
        info.append({"shape": t.vec(0, "i"), "buf": t.u32(2),
                     "scale": q.vec(2, "f") if q else [],
                     "zp": q.vec(3, "q") if q else []})
    for i, t in enumerate(info):
        print(f"  T{i} shape {t['shape']} buffer {t['buf']} "
              f"scale {t['scale'][:1]} zp {t['zp'][:1]}")

    inp, wt, bias, outp = info[0], info[1], info[2], info[3]
    OC, KH, KW, IC = wt["shape"]
    if (KH, KW) != (3, 3):
        print("  not a 3x3 conv, stopping")
        return

    w_zp = int(wt["zp"][0])
    w_sc = float(wt["scale"][0])
    in_sc, out_sc = float(inp["scale"][0]), float(outp["scale"][0])
    step = w_sc * in_sc / out_sc
    # An effective weight of one is not always representable: conv0's step is
    # 0.00725 per code, so unity would need code 289. Clamp to the largest
    # legal code instead of bailing. The response is still a single tap, only
    # scaled, and the CPU reference is computed from the same patched file, so
    # the comparison stays exact and correlation does not care.
    v = min(255, w_zp + int(np.floor(1.0 / step)))
    print(f"\n  weight zp {w_zp} scale {w_sc:.8f}, in {in_sc:.8f} out {out_sc:.8f}")
    print(f"  impulse code {v}, effective weight {(v - w_zp) * step:.4f}")
    if not 0 <= v <= 255 or v == w_zp:
        print("  impulse code unusable, stopping")
        return

    woff, wlen = bufs[wt["buf"]].data_span(0)
    boff, blen = bufs[bias["buf"]].data_span(0)
    print(f"  weight buffer at 0x{woff:x} length {wlen} (expect {OC*KH*KW*IC})")
    print(f"  bias buffer   at 0x{boff:x} length {blen} (expect {4*OC})")
    if wlen != OC * KH * KW * IC or blen != 4 * OC:
        print("  buffer sizes are not what the shapes say, stopping")
        return

    # tflite conv weights are [oc, ky, kx, ic]
    # mode "kx0".."kx2": every channel's live tap in ONE kernel column, with
    # the real bias kept. fc_impb's six wrong channels are exactly six of the
    # nine whose tap is kx = 2, and fc_imp with the same taps and no bias is
    # 32/32, so the bias is not the fault: it lifts the output clear of the
    # ReLU clip where the fault is visible. These isolate the column.
    kxfix = int(mode[2:]) if mode.startswith("kx") else None
    for o in range(OC):
        want_ic = o % IC
        want_p = (o // IC) % (KH * KW)
        if kxfix is not None:
            want_p = ((o // IC) % KH) * KW + kxfix
        for ky in range(KH):
            for kx in range(KW):
                for c in range(IC):
                    idx = woff + ((o * KH + ky) * KW + kx) * IC + c
                    on = ((c == want_ic) and (ky * KW + kx == want_p)
                          if mode != "all" else True)
                    b[idx] = v if on else w_zp
    if mode != "bias" and kxfix is None:
        b[boff:boff + blen] = b"\x00" * blen

    open(dst, "wb").write(bytes(b))
    print(f"\n  wrote {dst}  (mode {mode})")
    print("  output channel c should equal input plane c mod 3, shifted by "
          "tap (c/3) mod 9")
    print("  first 8: " + ", ".join(
        f"c{o}->ic{o % IC} tap{(o // IC) % 9}" for o in range(8)))


if __name__ == "__main__":
    main()
