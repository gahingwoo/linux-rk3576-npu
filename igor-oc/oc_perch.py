#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
# Derived from perch.py by Jiaxing Hu (GPL-2.0).
# oc_perch.py - score the NPU (teflon delegate) against the CPU interpreter
# PER OUTPUT CHANNEL, using the RAW CPU reference.
#
# Deliberately NOT max(cpu, output_zero_point). Clamping the reference to the
# zero point can hide a real difference, and it also invents one where the
# hardware does not clamp. The models mk1x1.py emits use zp_out = 0, which
# neutralises the question anyway, but the raw reference is the honest default.
#
# A channel "matches" when its maximum absolute difference against the
# reference over the whole surface is at most 1. That is the same rule
# perch.py uses.
#
# Two guards are printed on every run, because both have caught a false
# positive before:
#   - constant reference channels: must be 0. A channel whose reference never
#     varies matches trivially and proves nothing.
#   - NPU channels pinned at the output zero point: if this is large, the
#     comparison is measuring a clamp rather than arithmetic.
#
# Derived from perch.py by Jiaxing Hu (GPL-2.0), cut down to this one case.
#
# Usage:  TEFLON_LIB=/path/to/libteflon.so python3 oc_perch.py model.tflite ...
#         ROCKET_SEED=7 is the default input seed.
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB")
if not teflon:
    raise SystemExit("set TEFLON_LIB to the path of libteflon.so")
seed = int(os.environ.get("ROCKET_SEED", "7"))
print(f"# TEFLON_LIB={teflon}  ROCKET_SEED={seed}")

for model in sys.argv[1:]:
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    npu.allocate_tensors()
    ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
    n_in = int(np.prod(ni["shape"]))
    data = ((np.arange(n_in) * seed) % 251).astype(np.int64)
    npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
    npu.invoke()
    got = npu.get_tensor(no["index"])[0].astype(int)

    cpu = tflite.Interpreter(model_path=model)
    cpu.allocate_tensors()
    ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
    cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
    cpu.invoke()
    ref = cpu.get_tensor(co["index"])[0].astype(int)      # RAW, not clamped
    out_zp = int(co["quantization"][1])

    oc = got.shape[-1]
    g = got.reshape(-1, oc)
    r = ref.reshape(-1, oc)
    diff = np.abs(g - r).max(axis=0)                      # max diff per channel
    exact = int(np.sum(diff == 0))
    close = int(np.sum(diff <= 1))
    bad = [int(c) for c in np.nonzero(diff > 1)[0]]
    ref_const = int(np.sum(r.max(0) == r.min(0)))
    npu_pinned = int(np.sum((g.max(0) == g.min(0)) & (g.max(0) == out_zp)))

    name = os.path.basename(model)
    print(f"{name}: out{tuple(got.shape)} oc={oc}")
    print(f"  bit exact (diff==0): {exact}/{oc}   diff<=1: {close}/{oc}   "
          f"global maxdiff={int(diff.max())}")
    print(f"  constant reference channels: {ref_const} (must be 0)   "
          f"NPU channels pinned at zero point: {npu_pinned}")
    if bad:
        print(f"  BAD channels (diff>1): {len(bad)} -> {bad[:16]}"
              f"{' ...' if len(bad) > 16 else ''}")
        for c in bad[:4]:
            print(f"    ch{c}: maxdiff={int(diff[c])} "
                  f"npu[min,max]=[{g[:,c].min()},{g[:,c].max()}] "
                  f"cpu[min,max]=[{r[:,c].min()},{r[:,c].max()}]")
    np.savez(os.path.splitext(model)[0] + "-result.npz",
             npu=got, cpu=ref, diff=diff)
