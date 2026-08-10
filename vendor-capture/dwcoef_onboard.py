#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Decode the captured vendor coefficient buffers ON THE BOARD and print a verdict.

The point is to make a vendor capture behave like every other round: flash,
boot, read the console. Previously it meant flashing, booting, pulling files off
the second SD partition and decoding them on the host.

No numpy here, the capture rootfs does not have it, so the reference vectors are
baked in as literals. They come from sv_pairs.py's dw pair: ic = oc = 32 at
112x112, k=3, s=1, one calibration set, only `groups` differing, weights and
bias from RandomState(7). Because those are known exactly, a captured buffer can
be decoded rather than stared at.

The method is the one that worked on the .rknn files, including the two oracle
bugs its positive control caught: correlate every per-channel column, under FLAT
and BLOCKED layouts, against the bias, the per-channel weight sum, and the
per-channel-scaled forms, since A = bias - (in_zp - 0x80) * sw and with
per-channel quantisation A is proportional to neither term alone.

⚠ sv_rgu is the POSITIVE CONTROL and is reported first. Its A column has to come
back correlating with the weight sum, as it does in the .rknn at +0.9972. If it
does not, the capture is not what this expects and the depthwise answer below it
means nothing.

Usage: dwcoef_onboard.py <capture_dir> rg|dw
"""
import os
import struct
import sys

BIAS = [0.084526286, -0.023296868, 0.0016410082, 0.020375814, -0.039446153, 0.00010327865, -4.4519293e-05, -0.087736212, 0.050882902, 0.030024925, -0.03127145, -0.0085774129, 0.025264969, -0.013067821, -0.012137454, -0.07266207, 0.027729016, 0.0061940453, 0.013722996, -0.076326229, 0.082534984, 0.0077167768, -0.019356998, 0.10145361, -0.0022693016, -0.072533935, -0.020261392, -0.11441576, 0.052469827, -0.020823715, -0.037127677, 0.053623505]
SW_DW = [-0.10455874, -0.12005404, 0.082669124, -0.23992516, 0.23234206, -0.078529835, 0.29279959, 0.057390369, 0.30622435, -0.082272127, 0.23639634, -0.51287651, -0.40033114, -0.064245418, 0.23393053, -0.17066593, 0.1924755, -0.14507729, -0.18297473, -0.15005916, 0.01744451, 0.071013108, 0.1811765, -0.015217192, -0.086778477, 0.14451, 0.13513958, -0.49294731, 0.10639656, 0.21872558, -0.20997293, 0.061923444]
BIAS_OVER_SC_DW = [64.999275, -16.454823, 1.3624868, 16.967644, -41.655022, 0.092212416, -0.0462051, -61.630314, 47.025204, 27.274656, -51.486622, -6.9758172, 32.253777, -11.565903, -10.358941, -107.71486, 33.231495, 5.3042488, 10.555919, -90.179604, 220.90384, 7.0390491, -26.233061, 84.773354, -2.5706098, -65.223167, -23.090422, -78.794174, 62.097797, -17.987673, -37.11018, 29.753691]
SW_OVER_SC_DW = [-80.403893, -84.795433, 68.638046, -199.79396, 245.35255, -70.115417, 303.88699, 40.313873, 283.00787, -74.736038, 389.21283, -417.11093, -511.07095, -56.86153, 199.65247, -252.99661, 230.66988, -124.23643, -140.74669, -177.29523, 46.69001, 64.776367, 245.53467, -12.715293, -98.30056, 129.94469, 154.00867, -339.47577, 125.91983, 188.93671, -209.87398, 34.35902]
SW_RG = [-2.1238692, -1.311295, 1.3205793, 0.690548, -2.4965696, -2.3463094, 1.0870073, 2.9671307, -1.3626733, -1.7201433, -0.94019401, 0.90370494, 0.027984262, -2.7037282, -0.73062903, 0.25128353, -0.035628676, -0.88374329, 0.90452147, -0.47201794, -0.42474717, 0.6340723, 0.93497115, -1.153741, -2.1244586, 1.1513336, -0.39907849, 0.3200044, -0.99211478, 1.5260032, 1.9648108, 0.36613208]
BIAS_OVER_SC_RG = [43.531311, -12.326627, 0.80021143, 10.755903, -16.730587, 0.04684332, -0.022606801, -49.67495, 23.64842, 15.625384, -14.534059, -3.8526447, 11.272028, -7.3319383, -6.1864824, -39.070011, 13.611471, 3.1037271, 7.0511308, -37.436096, 38.821014, 4.3573503, -9.0637093, 53.397732, -1.112782, -37.764904, -10.507993, -72.202637, 25.065275, -9.9176064, -20.93527, 34.040157]
SW_OVER_SC_RG = [-1093.7996, -693.8205, 643.95941, 364.52371, -1058.8884, -1064.1979, 551.97992, 1679.9457, -633.31824, -895.18628, -436.97476, 405.90958, 12.485247, -1516.9758, -372.40295, 135.11383, -17.489214, -442.82822, 464.75995, -231.51294, -199.78336, 358.03485, 437.79034, -607.24457, -1041.7563, 599.4436, -206.97067, 201.94038, -473.9415, 726.78192, 1107.9025, 232.42035]


def corr(x, y):
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    sx = sum((v - mx) ** 2 for v in x) ** 0.5
    sy = sum((v - my) ** 2 for v in y) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (sx * sy)


def layouts(n=32):
    """(label, index list) for every per-channel column worth trying.

    The blocked one is what the regular conv actually uses, channel i at
    (i//8)*64 + (i%8)*4; a flat stride never reaches it, which is one of the
    two bugs the positive control caught on the host.
    """
    for block, G in ((64, 8), (64, 16), (32, 8), (128, 16)):
        for elem in (2, 4):
            if G * elem > block:
                continue
            for base in range(0, block - elem + 1, 2):
                yield (f"block {block} group {G} elem {elem} +{base}",
                       elem, [base + (i // G) * block + (i % G) * elem
                              for i in range(n)])
    for elem in (2, 4):
        for base in range(0, 16, 2):
            yield (f"flat elem {elem} +{base}", elem,
                   [base + i * elem for i in range(n)])


def scan(path, which):
    refs = {"bias": BIAS}
    if which == "rg":
        refs.update({"weight sum": SW_RG, "bias/wt_sc_c": BIAS_OVER_SC_RG,
                     "sw/wt_sc_c": SW_OVER_SC_RG})
    else:
        refs.update({"weight sum": SW_DW, "bias/wt_sc_c": BIAS_OVER_SC_DW,
                     "sw/wt_sc_c": SW_OVER_SC_DW})

    hits = []
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".bin"):
            continue
        raw = open(os.path.join(path, fn), "rb").read()
        # Bound the work: the coefficient buffer is a few KB, and the input
        # and output surfaces in the same dump are hundreds of KB and cannot
        # hold a 32-entry per-channel table anyway. Scanning them would turn a
        # few seconds of pure Python on a slow core into many minutes.
        if len(raw) < 256 or len(raw) > 65536:
            print(f"    (skip {fn}, {len(raw)} bytes)", flush=True)
            continue
        print(f"    scanning {fn}, {len(raw)} bytes ...", flush=True)
        for label, elem, idx in layouts():
            span = idx[-1] + elem
            fmt = "<i" if elem == 4 else "<h"
            for start in range(0, len(raw) - span, 4):
                try:
                    vals = [struct.unpack_from(fmt, raw, start + o)[0]
                            for o in idx]
                except struct.error:
                    break
                for rn, rv in refs.items():
                    c = corr(vals, rv)
                    if abs(c) > 0.98:
                        hits.append((abs(c), fn, start, label, rn, c))
    hits.sort(reverse=True)
    return hits


d = sys.argv[1]
which = sys.argv[2]
hits = scan(d, which)
print(f"  {os.path.basename(d)}: {len(hits)} per-channel columns above 0.98",
      flush=True)
seen = set()
for a, fn, off, label, rn, c in hits:
    if (fn, rn) in seen:
        continue
    seen.add((fn, rn))
    print(f"    {fn} @0x{off:05x}  {label:28s} vs {rn:14s} corr {c:+.4f}",
          flush=True)
    if len(seen) >= 8:
        break
if not hits:
    print("    NONE above 0.98", flush=True)
if which == "rg":
    ok = any(rn == "weight sum" for _, _, _, _, rn, _ in hits)
    print(f"  CONTROL {'PASSES' if ok else 'FAILS'}: the regular capture "
          f"{'does' if ok else 'does NOT'} decode. "
          f"{'' if ok else 'Nothing below can be read.'}", flush=True)
