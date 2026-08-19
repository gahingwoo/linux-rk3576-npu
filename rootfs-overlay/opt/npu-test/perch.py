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

THE REFERENCE IS NOW THE RAW CPU OUTPUT. It used to be max(cpu, zp), because
the output stage floored everything at the output zero point and nothing this
driver wrote would move it. Round 249 fixed that floor, so the clamped
reference no longer describes the hardware: it reports a CORRECT output as zero
channels matching. Both scores are still printed, since every log before 249
was read against the clamped one. PERCH_CLAMPED_REF=1 restores the old primary
for comparing against those logs directly.

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
# ROCKET_SEED changes the input without changing anything else, so a repeat
# submit that recomputes and one that returns a stale output buffer can be told
# apart. Every earlier "byte exact N times in a row" measurement here fed the
# same input each time and could not.
seed = int(os.environ.get("ROCKET_SEED", "7"))
data = ((np.arange(n_in) * seed) % 251).astype(np.int64)
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"])[0].astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
raw = cpu.get_tensor(co["index"])[0].astype(int)
clamped = np.maximum(raw, int(co["quantization"][1]))
ref = clamped if os.environ.get("PERCH_CLAMPED_REF") else raw

# A classifier's output is (N,) not (H, W, C), and indexing it as a surface
# threw an IndexError that ended the run before the regression got to print.
# Treat it as a one pixel surface so every metric below still means something.
if got.ndim == 1:
    got = got.reshape(1, 1, -1)
    ref = ref.reshape(1, 1, -1)
    raw = raw.reshape(1, 1, -1)
    clamped = clamped.reshape(1, 1, -1)

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

# WHETHER IT IS BYTE EXACT, which "maxdiff <= 1" does not say. The cover letter
# for the kernel series has claimed byte exact more than once and the headline
# metric above tolerates an off by one, so print the strict count too and let
# the number decide the wording.
_ex_px = int((got == ref).sum())
_tot_px = int(got.size)
_ex_ch = sum(1 for _c in range(oc) if (got[:, :, _c] == ref[:, :, _c]).all())
print(f"    EXACT vs the same reference: {_ex_px}/{_tot_px} pixels, "
      f"{_ex_ch}/{oc} channels identical, "
      f"{'BYTE EXACT' if _ex_px == _tot_px else 'NOT byte exact'}", flush=True)
if got.shape[0] * got.shape[1] == 1:
    # ⚠ A ONE PIXEL SURFACE HAS NO SPATIAL VARIATION TO REPRODUCE, so every
    # channel is "constant" by definition and COMPUTED is 0 whatever the answer
    # is. MobileNet's classifier is 1x1x1001 and read 0 of 1001 COMPUTED for
    # twenty rounds, which was this criterion failing and not the result. What
    # separates a real answer from a constant here is the spread ACROSS
    # channels, so that is what gets printed.
    print(f"    ONE PIXEL OUTPUT: COMPUTED cannot apply. Across the {oc} "
          f"channels, npu has {len(np.unique(got))} distinct values and the "
          f"reference {len(np.unique(ref))}", flush=True)

    # ⚠ CHANNEL AGREEMENT IS NOT THE ANSWER TO THE QUESTION THIS MODEL ASKS.
    #
    # 1000 of 1001 channels within one count says the surfaces agree. It does
    # not say the two stacks name the same class, and on a classifier that is
    # the only thing anyone wants to know. The output is a quantised softmax
    # with about ten distinct values, so two classes can sit one count apart
    # and a difference of one is enough to swap them. That has been inferred
    # here for months and never once printed.
    top_n = min(5, oc)
    npu_top = np.argsort(-got.reshape(-1), kind="stable")[:top_n]
    cpu_top = np.argsort(-ref.reshape(-1), kind="stable")[:top_n]
    print(f"    TOP {top_n} npu {[(int(i), int(got.reshape(-1)[i])) for i in npu_top]}",
          flush=True)
    print(f"    TOP {top_n} cpu {[(int(i), int(ref.reshape(-1)[i])) for i in cpu_top]}",
          flush=True)
    print(f"    TOP 1 {'AGREES' if npu_top[0] == cpu_top[0] else 'DIFFERS'}"
          f"    top {top_n} as a set "
          f"{'AGREES' if set(npu_top.tolist()) == set(cpu_top.tolist()) else 'DIFFERS'}",
          flush=True)
else:
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

# ⚠ THE REFERENCE IS A CHOICE AND max(cpu, out_zp) IS NOT FREE.
#
# It was picked because the output min pins at out_zp in every run, as if the
# accumulator were being ReLU'd. For an operator whose quantised output range
# already starts at zero the clamp cannot move a uint8 pixel and the choice
# costs nothing. For one with out_zp in the middle of the range it rewrites
# every pixel below it, which is up to half the surface. Those channels then
# read as constant, drop out of COMPUTED, and a channel can be scored correct
# because two surfaces were flattened the same way rather than because the
# hardware reproduced one.
#
# tfl_ops.py says every model here is fused_activation NONE, and of the six in
# the regression set only conv2d-cal has out_zp 128. So the clamp is expected
# to move NOTHING on five of them, and only conv2d-cal can say anything. If a
# zero point model reports a nonzero footprint below, this reading is wrong.
# ⚠ THE INTERPRETER IS NOT GROUND TRUTH, and round 257 measured that directly.
#
# Computed offline against exact arithmetic, tflite's own requant reads HIGH on
# 14.41 percent of mn_dw1's pixels, 0.86 of mn_pw2's and 0.18 of mn_pw24's,
# while the board measured this driver differing from the interpreter on 14.38,
# 0.78 and 0.19 percent of the same pixels, every one of them the other way. On
# those three the hardware is the accurate one and the reference is not, so a
# knob that improves agreement with the interpreter makes the driver worse.
#
# For a single operator model this scores against what the operation means
# instead. Anything else, and any failure, leaves the rest of the report alone.
try:
    from exactref import exact_reference

    _ex, _why = exact_reference(model, data.astype(np.uint8))
    if _ex is None:
        print(f"    EXACT ARITHMETIC reference: not computed, {_why}", flush=True)
    else:
        _ex = _ex.reshape(got.shape)
        _bad_ex = [c for c in range(oc)
                   if int(np.abs(got[:, :, c] - _ex[:, :, c]).max()) > 1]
        _px = int((got == _ex).sum())
        _tf = int((raw.reshape(got.shape) != _ex).sum())
        print(f"    EXACT ARITHMETIC reference: {oc - len(_bad_ex)}/{oc} channels "
              f"match, {_px}/{got.size} pixels identical"
              f"{'  BYTE EXACT' if _px == got.size else ''}", flush=True)
        print(f"      the tflite interpreter itself differs from exact on "
              f"{_tf}/{got.size} pixels", flush=True)
        if _tf:
            _rf = raw.reshape(got.shape)
            _d = _rf != _ex
            print(f"      of those the interpreter reads HIGH "
                  f"{100.0 * (_rf[_d] > _ex[_d]).mean():.1f}%", flush=True)
except Exception as _e:
    print(f"    exact reference unavailable: {type(_e).__name__} {_e}", flush=True)

moved = int((raw != clamped).sum())
if moved == 0:
    print(f"    UNCLAMPED reference: identical, the clamp moves no pixel here",
          flush=True)
else:
    bad_raw = [c for c in range(oc)
               if int(np.abs(got[:, :, c] - raw[:, :, c]).max()) > 1]
    raw_flat = np.array([len(np.unique(raw[:, :, c])) == 1 for c in range(oc)])
    good_raw = np.array([c not in bad_raw for c in range(oc)])
    ch_moved = sum(1 for c in range(oc)
                   if (raw[:, :, c] != clamped[:, :, c]).any())
    px = got.shape[0] * got.shape[1] * oc
    print(f"    UNCLAMPED reference: the clamp rewrites {moved}/{px} pixels "
          f"across {ch_moved}/{oc} channels", flush=True)
    one_px = got.shape[0] * got.shape[1] == 1
    # ⚠ Both rows must be scored against their OWN reference. Since round 249
    # the primary is the raw CPU output, so `bad` is already the unclamped
    # score and reusing it here would print the same number twice under two
    # names.
    bad_cl = [c for c in range(oc)
              if int(np.abs(got[:, :, c] - clamped[:, :, c]).max()) > 1]
    cl_flat = np.array([len(np.unique(clamped[:, :, c])) == 1
                        for c in range(oc)])
    for name, b, fl in (("vs UNCLAMPED cpu", bad_raw, raw_flat),
                        ("vs max(cpu,zp) ", bad_cl, cl_flat)):
        ok = np.array([c not in b for c in range(oc)])
        comp = "n/a" if one_px else str(int((ok & ~fl).sum()))
        print(f"      {name}: {oc - len(b)}/{oc} channels match    "
              f"COMPUTED {comp}    reference constant {int(fl.sum())}/{oc}",
              flush=True)
    if len(bad_raw) > len(bad):
        print(f"      {len(bad_raw) - len(bad)} channels agree with the "
              f"reference ONLY because both sides were clamped", flush=True)
    print(f"      cpu unclamped min={raw.min()} max={raw.max()} "
          f"distinct={len(np.unique(raw))}", flush=True)
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
    # A 1x1 output has no interior. MobileNet's classifier is 1x1x1001 and
    # this crashed on it for every round it was run, after the useful lines had
    # already printed, so it looked like a tail of noise rather than a bug here.
    inner = (np.abs(got[1:-1, 1:-1] - ref[1:-1, 1:-1]).max()
             if got.shape[0] > 2 and got.shape[1] > 2 else -1)
    print(f"    maxdiff excluding the outer ring: {int(inner)}"
          f"    whole surface: {int(np.abs(got - ref).max())}", flush=True)
    # WHICH edge. "excluding the outer ring" strips all four at once, so a
    # maxdiff of 1 inside and 255 overall says only that the damage is on the
    # ring, not which side of it. That distinction decides the question: with
    # tflite SAME on 224 at stride 2, the single pad lands AFTER, so the last
    # output row and the last output column are the only ones that read a
    # padded tap. The first row and the first column read nothing padded at
    # all. If the damage is on the last row and last column, it is padding;
    # if it is on the first, padding cannot explain it.
    def _reg(name, sl):
        d = np.abs(got[sl] - ref[sl])
        # A 1x1 surface has no interior, so this slice is empty and max() on it
        # raises. Round 205 guarded the other one of these and missed this one,
        # and the traceback still landed after every useful line had printed.
        if d.size == 0:
            return f"{name} EMPTY"
        return f"{name} max {int(d.max())} off>1 {int((d > 1).sum())}"
    print("    by edge: "
          + " | ".join([_reg("row0", (slice(0, 1), slice(None))),
                        _reg("rowN", (slice(-1, None), slice(None))),
                        _reg("col0", (slice(None), slice(0, 1))),
                        _reg("colN", (slice(None), slice(-1, None))),
                        _reg("interior", (slice(1, -1), slice(1, -1)))]),
          flush=True)

# When a channel correlates but disagrees, NAME THE AFFINE MAP.
#
# fc_imp decodes to exactly the right input plane and tap on all 32 channels at
# correlation 1.000 and still matches nothing, which can only be a scale and an
# offset. Sweeping blindly for those wastes a flash each time; fitting them
# from the two surfaces says what to write. ref = a * npu + b, per channel,
# reported as the median so one saturated channel cannot move it.
if bad:
    aa, bb, rr, fit_ch = [], [], [], []
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
        fit_ch.append(c)
    if aa:
        aa, bb, rr = np.array(aa), np.array(bb), np.array(rr)
        print(f"    affine fit over {len(aa)} wrong channels, unclipped "
              f"pixels only, ref = a*npu + b:"
              f"  a median {np.median(aa):.4f} (min {aa.min():.4f} max "
              f"{aa.max():.4f})", flush=True)
        print(f"      b median {np.median(bb):+.2f}    correlation median "
              f"{np.median(rr):+.4f}", flush=True)
        # IS THE OFFSET THE SAME ON EVERY CHANNEL, which is the whole question
        # once the slope is 1 and the correlation is 0.996: a single global
        # constant is a bias term, and one that moves per channel is the
        # per-channel A record. Round 198 left pw33x64w56 at a = 0.9985 and
        # b = -31.46 with nothing but that constant wrong.
        print(f"      b spread: min {bb.min():+.2f} max {bb.max():+.2f} "
              f"std {bb.std():.2f}   {'SAME on every channel' if bb.std() < 0.5 else 'VARIES per channel'}",
              flush=True)
        srt = np.argsort(bb)
        print("      b per channel, lowest 4: " +
              ", ".join(f"ch{fit_ch[i]}={bb[i]:+.1f}" for i in srt[:4]) +
              "   highest 4: " +
              ", ".join(f"ch{fit_ch[i]}={bb[i]:+.1f}" for i in srt[-4:]),
              flush=True)
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
# The off-by-one population. IT IS THE REFERENCE, NOT THE HARDWARE.
#
# Read this before treating a number here as a defect. The whole population was
# solved on 2026-08-12 and it is tflite's own double rounding:
#
#   model                exact% here   off by one   direction
#   mn_dw1                    85.50        56125    npu low, all of it
#   mn_dw25                   99.66           86    npu low
#   mn_conv0                  99.80          773    npu low
#   conv2d-cal                99.99           10    npu high
#
# Emulating tflite's integer requant offline, SaturatingRoundingDoublingHighMul
# then RoundingDivideByPOT, and comparing it against the hardware's half-up
# shift reproduces every one of those figures to the pixel. Comparing the
# hardware against exact real arithmetic instead gives 99.97 to 99.99 percent
# on all four. The hardware is the accurate one.
#
# The mechanism is tflite's shift. For mn_dw1 the multiplier is 0.2922, so
# tflite's shift is -1 and its final divide is by two: the intermediate carries
# a single bit below the answer, lands on exactly one half for half the pixels,
# and rounds up every time. mn_conv0's shift is -7 and conv2d-cal's is -10, and
# their populations shrink accordingly.
#
# So a one sided lean here is EXPECTED and is not a lead. maxdiff <= 1 is the
# pass mark and always was. What this print is still good for is a CHANGE: if a
# model's figure moves after a driver change, something real moved.
gi, ri = got[1:-1, 1:-1], ref[1:-1, 1:-1]
if gi.size == 0:          # a 1x1 surface has no interior; use the whole thing
    gi, ri = got, ref
di = ri - gi
one = np.abs(di) == 1
n1 = int(one.sum())
print(f"    interior: exact {100.0 * (di == 0).sum() / di.size:5.2f}%   "
      f"off by exactly 1: {n1}"
      + (f", of which npu LOW {100.0 * (di[one] > 0).sum() / n1:5.1f}%"
         if n1 else ""), flush=True)
# WHERE the off-by-ones sit, by row and by channel.
#
# mn_dw1 is 85.50% interior exact with every one of its 56125 off-by-ones in
# the same direction, against 99.66% on mn_dw25 and 99.99% on conv2d-cal. All
# four models here are per-TENSOR quantised, one scale per tensor, so the Q4
# per-channel coefficient cannot be the difference: C is 16 for every channel
# in all of them. What is different about mn_dw1 is that it is the only one
# dispatched as TWO row windows.
#
# A rate that jumps at one row is a seam between those windows. A rate that is
# flat across rows but varies by channel is per channel. A rate flat in both is
# the requant arithmetic itself.
if n1:
    rr = one.mean(axis=(1, 2))
    cc = one.mean(axis=(0, 1))
    med = float(np.median(rr))
    print(f"    off-by-1 by row, every 8th: "
          f"{[round(float(v), 3) for v in rr[::8]]}", flush=True)
    hot = np.nonzero(rr > 2 * med + 1e-9)[0]
    if len(hot) and len(hot) < len(rr):
        print(f"      rows above twice the median rate: {len(hot)}, "
              f"first {hot[:4].tolist()} last {hot[-4:].tolist()}", flush=True)
    order = np.argsort(cc)
    print(f"    off-by-1 by channel: median {float(np.median(cc)):.3f}"
          f"   lowest {[(int(c), round(float(cc[c]), 3)) for c in order[:3]]}"
          f"   highest {[(int(c), round(float(cc[c]), 3)) for c in order[-3:]]}",
          flush=True)
    # RAW SAMPLES, so the requant can be solved instead of guessed at.
    #
    # Round 100 spent a flash on one candidate bit, DPU 0x4044, and it did
    # nothing in either direction. Six more registers differ between the
    # depthwise and regular emissions and sweeping them one per flash is six
    # more rounds for a question that does not need them: the offline model
    # already reproduces the CPU reference exactly from the model file and this
    # very input, so given the hardware's own numbers at known coordinates the
    # map from accumulator to output can be solved outright.
    #
    # Two rows of sixteen from the worst channel is enough to pin a multiplier,
    # a shift and a rounding constant, and the coordinates are fixed so the
    # accumulator can be recomputed for exactly these pixels.
    wc = int(order[-1])
    # ⚠ EVERY HARDCODED COORDINATE IN THIS FILE ASSUMES A SURFACE. Rows 1 and 2
    # and columns 1 to 16 do not exist on a 1x1x1001 classifier, and this raised
    # IndexError on MobileNet after the useful lines had printed, which is round
    # 206's third crash from the same assumption. The rule that round said out
    # loud was to stop patching call sites one at a time, so the three places
    # that index space are listed here and all of them are guarded:
    #
    #   line ~156  inner maxdiff       guarded, prints -1
    #   line ~299  interior stats      guarded, falls back to the whole surface
    #   here       the RAW row dump    guarded below
    rows = [y for y in (1, 2) if y < got.shape[0]]
    cols = min(17, got.shape[1])
    if not rows or cols <= 1:
        print(f"    RAW ch {wc}: surface is {got.shape[0]}x{got.shape[1]}, "
              f"no rows 1,2 cols 1..16 to show; whole channel is "
              f"npu {got[:, :, wc].ravel().tolist()[:16]} "
              f"ref {ref[:, :, wc].ravel().tolist()[:16]}", flush=True)
    else:
        print(f"    RAW ch {wc} rows {rows} cols 1..{cols - 1}", flush=True)
        for y in rows:
            g = got[y, 1:cols, wc].tolist()
            r = ref[y, 1:cols, wc].tolist()
            print(f"      y{y} npu {g}", flush=True)
            print(f"      y{y} ref {r}", flush=True)

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
