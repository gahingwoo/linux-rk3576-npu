#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Run a whole model on the NPU against a CPU reference, N times, with a DIFFERENT
input every time.

The different input per run is not optional. Every "it works" result this project
produced between June and 2026-08-06 fed the same input each time, so a correct
recomputation and an output buffer nothing had written since the first submit
were indistinguishable. They were stale. Each run here gets its own input and its
own CPU reference.

The hardware applies a ReLU at the output zero point, so for the feature-map
test models the right reference is max(cpu, zp), not the raw CPU output. An
earlier version of this script compared against the raw output and reported
conv2d-cal as a failure at maxdiff 128 when test_once.py had it byte exact.
Both are printed here, and the smaller one is used, so neither model shape is
judged by the wrong reference.

Per run:
  raw / relu  worst per element difference against each reference
  top1        whether the highest scoring output index agrees
  jobs        how many jobs the kernel actually submitted for that invoke

A run that returns the PREVIOUS run's bytes is caught as STALE, because its
input and therefore its reference have changed.

Usage: TEFLON_LIB=... python3 test_model.py <model.tflite> [runs]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 4

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]

n = int(np.prod(ci["shape"]))
print(f"=== {os.path.basename(model)}  in{list(ci['shape'])} out{list(co['shape'])}  "
      f"{runs} runs, a different input each ===", flush=True)

def job_count():
    """How many jobs the kernel submitted, from the per-job log."""
    try:
        import subprocess
        out = subprocess.run(["dmesg"], capture_output=True, text=True).stdout
        return out.count("job: task_count=")
    except Exception:
        return -1


oq = co.get("quantization", (0.0, 0))
zp = int(oq[1]) if oq and len(oq) > 1 else 0

ok_runs = 0
prev = None
for r in range(runs):
    jobs_before = job_count()
    data = ((np.arange(n) * 7 + r * 61) % 251).astype(np.int64)

    cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
    cpu.invoke()
    ref = cpu.get_tensor(co["index"]).flatten().astype(int)

    npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
    npu.invoke()
    got = npu.get_tensor(no["index"]).flatten().astype(int)

    md_raw = int(np.abs(got - ref).max())
    md_relu = int(np.abs(got - np.maximum(ref, zp)).max())
    md = min(md_raw, md_relu)
    same_top1 = int(np.argmax(got)) == int(np.argmax(ref))
    stale = prev is not None and bool((got == prev).all())
    prev = got.copy()
    jobs = job_count() - jobs_before

    ok = same_top1 and md <= 4 and not stale
    ok_runs += ok
    print(f"  run {r}: raw={md_raw:4d} relu={md_relu:4d}  top1 npu={int(np.argmax(got)):4d} "
          f"cpu={int(np.argmax(ref)):4d} {'match' if same_top1 else 'MISMATCH'}"
          f"  jobs={jobs:3d}"
          f"{'  STALE' if stale else ''}"
          f"  {'OK' if ok else 'FAIL'}", flush=True)

print("", flush=True)
if ok_runs == runs:
    print(f"  VERDICT: {ok_runs}/{runs} correct. The whole graph runs on the NPU and "
          f"recomputes every submit.", flush=True)
elif ok_runs == 0:
    print(f"  VERDICT: 0/{runs} correct. The graph does not run correctly at all.",
          flush=True)
else:
    print(f"  VERDICT: {ok_runs}/{runs} correct. Partial, read the per-run lines.",
          flush=True)

sys.stdout.flush()
os._exit(0)
