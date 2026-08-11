#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Report which OUTPUT CHANNELS match the CPU, instead of one number for the model.

Round 29 showed the 256 bytes at groups*64 must hold exactly mesa's float32
dequantised weights: zeroing them fails and so does writing a correct
per-channel fp16 weight scale, with the rest of the float surface proven
present. A single pass/fail cannot say WHY, and the offline work says the vendor
treats that address as one entry per output channel.

So ask the question at channel granularity. 256 bytes is

    2 bytes x 128 channels    the vendor's layout, every channel affected
    4 bytes x  64 channels    then only channels 0..63 should break
    something not per-channel then the damage will not follow channel
                              boundaries at all

The shape of the answer names the element size directly, which no amount of
guessing at values has managed.

The hardware ReLUs at the output zero point, so the reference is max(cpu, zp),
the same one test_model.py uses.

Usage: TEFLON_LIB=... perch.py <model.tflite>
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]

n_in = None
deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
n_in = int(np.prod(ni["shape"]))
data = ((np.arange(n_in) * 7) % 251).astype(np.int64)
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"])[0].astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
ref = np.maximum(cpu.get_tensor(co["index"])[0].astype(int),
                 int(co["quantization"][1]))

oc = got.shape[2]
bad = []
worst = []
for c in range(oc):
    d = int(np.abs(got[:, :, c] - ref[:, :, c]).max())
    worst.append(d)
    if d > 1:
        bad.append(c)

# Distinguish "the MAC never fired" from "the MAC fired with wrong operands".
# A surface pinned at the output zero point is an empty convolution; a varying
# surface that disagrees with the reference is a wrong one. Those need
# completely different next steps, and a maxdiff cannot tell them apart.
ozp = int(co["quantization"][1])
flat_ch = sum(1 for c in range(got.shape[2])
              if len(np.unique(got[:, :, c])) == 1)
at_zp = sum(1 for c in range(got.shape[2])
            if len(np.unique(got[:, :, c])) == 1 and got[0, 0, c] == ozp)

# ⚠ A matching channel is not necessarily a computed one.
#
# On mn_dw1 the nine channels reported as matching were exactly the nine with
# the largest |A|, and a channel whose A is large enough saturates the requant
# to a single value for the whole surface. If the CPU reference saturates too,
# the two agree and the channel is scored correct without a single multiply
# having to be right. Round 55's 9 of 32 could be almost entirely that.
#
# So split the count. A channel is only counted as COMPUTED if the reference
# actually varies across it: then agreeing means reproducing a surface, which
# no constant can do by accident.
ref_flat = np.array([len(np.unique(ref[:, :, c])) == 1 for c in range(oc)])
npu_flat = np.array([len(np.unique(got[:, :, c])) == 1 for c in range(oc)])
good = np.array([c not in bad for c in range(oc)])
computed = int((good & ~ref_flat).sum())
trivial = int((good & ref_flat).sum())
print(f"  {os.path.basename(model)} out{got.shape}: {oc - len(bad)}/{oc} "
      f"channels match (maxdiff <= 1)", flush=True)
print(f"    of those, COMPUTED (reference varies): {computed}    "
      f"trivial (reference is constant): {trivial}", flush=True)
print(f"    npu distinct={len(np.unique(got))} min={got.min()} max={got.max()} "
      f"| cpu distinct={len(np.unique(ref))} | out_zp={ozp}", flush=True)
print(f"    channels that are CONSTANT: {flat_ch}/{oc}, "
      f"of which pinned at out_zp: {at_zp}  "
      f"({'EMPTY conv' if at_zp == oc else 'not empty'})", flush=True)
print(f"    reference channels that are constant: {int(ref_flat.sum())}/{oc}"
      f"    npu constant but reference varies: "
      f"{int((npu_flat & ~ref_flat).sum())}", flush=True)
# WHERE in the surface the error is, which the channel view cannot show.
#
# The impulse run decoded 27 of 32 channels to exactly the right tap of exactly
# the right input plane at correlation +1.000, the same answer the CPU gives,
# and the other five are the decoder aliasing on a ramp rather than the
# hardware. Yet the same run is 0 of 32 on maxdiff, with the hardware's value
# range identical to the reference's. Perfect correlation on an interior crop
# plus a large maxdiff over the whole surface means the error is somewhere the
# crop did not look.
#
# The row profile says where. mesa splits these depthwise layers into TWO
# tasks, visible as two OUT_CVT lines in the log, while conv2d-cal emits one,
# so a seam between row windows is a candidate no coefficient sweep could have
# reached.
rowerr = np.abs(got - ref).max(axis=(1, 2))
colerr = np.abs(got - ref).max(axis=(0, 2))
nzr = np.nonzero(rowerr)[0]
nzc = np.nonzero(colerr)[0]
print(f"    rows with any error: {len(nzr)}/{got.shape[0]}"
      + (f", first {nzr[:6].tolist()} last {nzr[-6:].tolist()}" if len(nzr) else ""),
      flush=True)
print(f"    cols with any error: {len(nzc)}/{got.shape[1]}"
      + (f", first {nzc[:6].tolist()} last {nzc[-6:].tolist()}" if len(nzc) else ""),
      flush=True)
if len(nzr):
    print(f"    row maxdiff profile, every 8th: "
          f"{rowerr[::8].tolist()}", flush=True)
    inner = np.abs(got[1:-1, 1:-1] - ref[1:-1, 1:-1]).max()
    print(f"    maxdiff excluding the outer ring: {int(inner)}"
          f"    whole surface: {int(np.abs(got - ref).max())}", flush=True)

# When a channel correlates but disagrees, NAME THE AFFINE MAP.
#
# fc_imp decodes to exactly the right input plane and tap on all 32 channels at
# correlation 1.000 and still matches nothing, which can only be a scale and an
# offset. Sweeping blindly for those wastes a flash each time; fitting them
# from the two surfaces says what to write. ref = a * npu + b, per channel,
# reported as the median so one saturated channel cannot move it.
if bad:
    aa, bb, rr = [], [], []
    for c in bad:
        u = got[:, :, c].ravel().astype(float)
        v = ref[:, :, c].ravel().astype(float)
        # ⚠ Fit only where NEITHER surface is clipped.
        #
        # The reference is max(cpu, out_zp) and both surfaces saturate at 255,
        # so a fit over everything compares two differently clipped shapes and
        # cannot reach correlation 1 however right the underlying map is. That
        # is what made round 83 read 0.89 and call it a border error: with
        # pad_top and pad_left at 0 the padding touches one row and one column,
        # 1.8 percent of the surface, which cannot move a correlation that far.
        # Excluding clipped pixels is what makes a and b mean anything.
        keep = (v > ozp) & (v < 255) & (u > ozp) & (u < 255)
        if keep.sum() < 64:
            continue
        u, v = u[keep], v[keep]
        if u.std() == 0 or v.std() == 0:
            continue
        a = float(np.cov(u, v)[0, 1] / np.var(u))
        aa.append(a)
        bb.append(float(v.mean() - a * u.mean()))
        rr.append(float(np.corrcoef(u, v)[0, 1]))
    if aa:
        aa, bb, rr = np.array(aa), np.array(bb), np.array(rr)
        print(f"    affine fit over {len(aa)} wrong channels, unclipped "
              f"pixels only, ref = a*npu + b:"
              f"  a median {np.median(aa):.4f} (min {aa.min():.4f} max "
              f"{aa.max():.4f})", flush=True)
        print(f"      b median {np.median(bb):+.2f}    correlation median "
              f"{np.median(rr):+.4f}", flush=True)
        # WHICH channels are the outliers, so they can be looked at offline.
        #
        # conv0's fit has sat at a median 0.9991 with a minimum of 0.9486
        # through every change of the global multiplier, the overflow knob and
        # the weight fill. One channel five percent out while the rest are at
        # 1.000 is per channel, and naming it is the only way to ask what is
        # special about its weights or its bias.
        ch = np.array([c for c in bad
                       if not (np.std(got[:, :, c]) == 0
                               or np.std(ref[:, :, c]) == 0)])
        if len(ch) == len(aa):
            order = np.argsort(aa)
            worst = [(int(ch[i]), round(float(aa[i]), 4),
                      round(float(bb[i]), 1)) for i in order[:3]]
            best = [(int(ch[i]), round(float(aa[i]), 4),
                     round(float(bb[i]), 1)) for i in order[-3:]]
            print(f"      lowest a: {worst}", flush=True)
            print(f"      highest a: {best}", flush=True)

# HOW the residual is distributed, which a maxdiff cannot say.
#
# fc_allw fails every channel while its affine map is perfect, a identical
# across all 32 channels at correlation 1.0000, and mn_conv0 sits at a 0.9991
# with 0 COMPUTED. A surface that is uniformly two counts out and a surface
# that is exact apart from a handful of wild pixels both score maxdiff > 1 and
# need completely different next steps.
d = np.abs(got - ref)
tot = d.size
print(f"    residual: within 1 {100.0 * (d <= 1).sum() / tot:5.1f}%   "
      f"within 2 {100.0 * (d <= 2).sum() / tot:5.1f}%   "
      f"within 4 {100.0 * (d <= 4).sum() / tot:5.1f}%   "
      f"within 8 {100.0 * (d <= 8).sum() / tot:5.1f}%", flush=True)
sat = ((got >= 255) | (got <= ozp)) & (d > 1)
print(f"      of the pixels off by more than 1, {100.0 * sat.sum() / max(1, (d > 1).sum()):5.1f}% "
      f"are at a rail of the hardware output", flush=True)

if not bad:
    print("    every channel correct", flush=True)
else:
    # Print as runs so a clean 0..63 split is visible at a glance.
    runs, s = [], bad[0]
    for i in range(1, len(bad)):
        if bad[i] != bad[i - 1] + 1:
            runs.append((s, bad[i - 1])); s = bad[i]
    runs.append((s, bad[-1]))
    txt = ", ".join(f"{a}" if a == b else f"{a}..{b}" for a, b in runs[:12])
    print(f"    WRONG channels ({len(bad)}): {txt}"
          f"{' ...' if len(runs) > 12 else ''}", flush=True)
    print(f"    first 8 channel maxdiffs: {worst[:8]}", flush=True)
    print(f"    channels 64..71 maxdiffs: {worst[64:72]}", flush=True)
    okl = [c for c in range(oc) if c not in bad and not ref_flat[c]]
    print(f"    COMPUTED-correct channels: {okl[:48]}"
          f"{' ...' if len(okl) > 24 else ''}", flush=True)

    # WHICH channels are alive, as runs.
    #
    # With one tap at the same position in every channel, exactly 128 of 1024
    # produce anything at all and 896 are flat, and that count does not change
    # when the tap moves from the centre to the corner. 128 is 1024/8. Whether
    # those 128 are a contiguous block or spread evenly is the difference
    # between a truncated weight fetch and a strided one, and nothing else in
    # this report can tell them apart.
    live = [c for c in range(oc) if not npu_flat[c]]
    if live and len(live) < oc:
        runs, st = [], live[0]
        for i in range(1, len(live)):
            if live[i] != live[i - 1] + 1:
                runs.append((st, live[i - 1])); st = live[i]
        runs.append((st, live[-1]))
        txt = ", ".join(f"{a}" if a == b else f"{a}..{b}" for a, b in runs[:10])
        print(f"    channels whose output VARIES ({len(live)}), as runs: {txt}"
              f"{' ...' if len(runs) > 10 else ''}", flush=True)
        print(f"      {len(runs)} runs; first live {live[0]}, last {live[-1]}",
              flush=True)

sys.stdout.flush()
os._exit(0)
