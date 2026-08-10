#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Decode a depthwise impulse run: say which tap and which channel the hardware
actually used, per output channel.

dw_imp.tflite is mn_dw1 with every weight set to the weight zero point except
one tap per channel at position c mod 9, and a zero bias. Its input and output
scales are equal, so the correct output of channel c is its own input shifted
by that tap. Anything else is a layout fact rather than a rounding one.

For every output channel this scores the hardware's surface against the input
shifted by all nine taps, for the channel's own input plane and for every other
plane, and prints what fits best. The CPU interpreter runs the same file, so
its answer is printed beside as the control: if the CPU's own decode is not the
identity mapping, the model is not what this script thinks it is and nothing
below it can be read.

Usage: TEFLON_LIB=... dwimp.py [model.tflite]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

model = sys.argv[1] if len(sys.argv) > 1 else "/opt/npu-test/dw_imp.tflite"
teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")

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
ref = cpu.get_tensor(co["index"])[0].astype(int)

x = data.reshape(ni["shape"])[0].astype(int)
H, W, C = x.shape


def shifted(plane, ky, kx):
    """The input plane as the tap at (ky, kx) sees it, SAME padding."""
    out = np.zeros_like(plane)
    ys, ye = max(0, 1 - ky), min(H, H + 1 - ky)
    xs, xe = max(0, 1 - kx), min(W, W + 1 - kx)
    out[ys:ye, xs:xe] = plane[ky - 1 + ys:ky - 1 + ye, kx - 1 + xs:kx - 1 + xe]
    return out


# A crop keeps the search cheap on the board and still holds 30x30 samples,
# which no wrong shift can fit by accident.
sl = (slice(8, 38), slice(8, 38))


def decode(surface, c):
    """Best (source channel, ky, kx) for this output channel."""
    best = (-2.0, None)
    for sc in range(C):
        for ky in range(3):
            for kx in range(3):
                cand = shifted(x[:, :, sc], ky, kx)[sl].ravel().astype(float)
                if cand.std() == 0:
                    continue
                v = surface[sl].ravel().astype(float)
                if v.std() == 0:
                    return (0.0, None)
                r = float(np.corrcoef(v, cand)[0, 1])
                if r > best[0]:
                    best = (r, (sc, ky, kx))
    return best


print(f"  {os.path.basename(model)} out{got.shape}")
print(f"  npu distinct={len(np.unique(got))}  cpu distinct={len(np.unique(ref))}")

hits_cpu = hits_npu = same_ch = 0
rows = []
for c in range(C):
    want = ((c % 9) // 3, (c % 9) % 3)
    rc, gc = decode(ref[:, :, c], c), decode(got[:, :, c], c)
    if rc[1] == (c, want[0], want[1]):
        hits_cpu += 1
    if gc[1] == (c, want[0], want[1]):
        hits_npu += 1
    if gc[1] is not None and gc[1][0] == c:
        same_ch += 1
    rows.append((c, want, rc, gc))

print(f"  CONTROL, the CPU decodes to its own impulse: {hits_cpu}/{C}")
print(f"  hardware decodes to the same impulse:        {hits_npu}/{C}")
print(f"  hardware reads its OWN input channel:        {same_ch}/{C}")
print("  ch  want      cpu says            npu says            corr")
for c, want, rc, gc in rows[:16]:
    print(f"  {c:3d} {str(want):9s} {str(rc[1]):19s} {str(gc[1]):19s} "
          f"{gc[0]:+.3f}")
sys.stdout.flush()
os._exit(0)
