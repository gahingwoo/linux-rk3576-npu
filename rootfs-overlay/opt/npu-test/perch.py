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

print(f"  {os.path.basename(model)} out{got.shape}: {oc - len(bad)}/{oc} "
      f"channels match (maxdiff <= 1)", flush=True)
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

sys.stdout.flush()
os._exit(0)
