#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
A -> B -> A. Does loading a second configuration poison the pipeline, or does the
first one survive?

Established 2026-07-26: re-running the SAME conv six times in one power session
is byte-exact every time (test_twice.py). So the wall is not "the second op
fails" -- it is "loading a different configuration fails". This narrows that.

Run model A (conv2d-cal, known byte-exact), then model B (a different conv),
then A again, all in ONE power session with both delegates alive so nothing is
torn down and no reset happens in between.

  A ok, B bad, A ok    -> only the NEW configuration fails to land; the resident
                          one is untouched. The defect is in the descriptor/
                          weight load for the incoming config.
  A ok, B bad, A bad   -> loading a second configuration poisons the pipeline
                          for everything, including a config that was working a
                          moment ago. The defect is destructive, not just a
                          failed load.
  A ok, B ok           -> B is not a valid "different configuration" for this
                          purpose (too similar, or it shares the resident set).
                          Pick a B with different shapes.

Oracle: the hardware applies a ReLU at the output zero point, so the reference is
max(CPU, out_zp), and out_zp comes from the model's quantisation params -- never
guessed from the data.

Usage: TEFLON_LIB=... python3 test_aba.py <modelA> <modelB>
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_a, model_b = sys.argv[1], sys.argv[2]


def ref_for(path):
    """CPU reference + relu reference + the input we will feed the NPU."""
    det = tflite.Interpreter(model_path=path)
    det.allocate_tensors()
    inp = det.get_input_details()[0]
    out = det.get_output_details()[0]
    n = int(np.prod(inp["shape"]))
    indata = (np.arange(n) % 251).astype(np.int64)
    det.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    det.invoke()
    cpu = det.get_tensor(out["index"])[0].flatten().astype(int)
    oq = out.get("quantization", (0.0, 0))
    zp = int(oq[1]) if oq and len(oq) > 1 else 128
    return indata, cpu, np.maximum(cpu, zp), zp


def npu_interp(path):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    it = tflite.Interpreter(model_path=path, experimental_delegates=deleg)
    it.allocate_tensors()
    return it


def run(it, indata):
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    it.invoke()
    return it.get_tensor(out["index"])[0].flatten().astype(int)


in_a, cpu_a, ref_a, zp_a = ref_for(model_a)
in_b, cpu_b, ref_b, zp_b = ref_for(model_b)

print(f"=== A={os.path.basename(model_a)} (zp {zp_a})  "
      f"B={os.path.basename(model_b)} (zp {zp_b}) ===", flush=True)

# Both interpreters built up front and kept alive: the point is that NOTHING is
# torn down between the three runs, so the NPU never loses power and the only
# event between A and A' is that B's configuration was loaded.
it_a = npu_interp(model_a)
it_b = npu_interp(model_b)

seq = [("A ", it_a, in_a, ref_a),
       ("B ", it_b, in_b, ref_b),
       ("A'", it_a, in_a, ref_a)]

results = []
for tag, it, indata, ref in seq:
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    exact = float((got == ref).mean() * 100)
    ok = md <= 2
    results.append((tag, ok, md, exact))
    print(f"  {tag}: distinct={len(np.unique(got)):3d} mean={got.mean():6.1f} "
          f"| vs RELU-ref maxdiff={md:3d} exact={exact:5.1f}%  {'OK' if ok else 'WRONG'}",
          flush=True)

a_ok, b_ok, a2_ok = (r[1] for r in results)
if a_ok and not b_ok and a2_ok:
    print("  VERDICT: only the INCOMING config fails to land; the resident one is")
    print("           untouched. Look at the descriptor/weight load for the new config.",
          flush=True)
elif a_ok and not b_ok and not a2_ok:
    print("  VERDICT: loading a second config POISONS the pipeline -- a config that")
    print("           worked a moment ago now fails. The load is destructive.", flush=True)
elif a_ok and b_ok:
    print("  VERDICT: B also computed. Either the wall needs a bigger config change,")
    print("           or B shares enough with A to reuse the resident set.", flush=True)
else:
    print(f"  VERDICT: unexpected {[(t, o) for t, o, _, _ in results]} -- read the lines.",
          flush=True)

sys.stdout.flush()
os._exit(0)          # skip interpreter GC; BO teardown is fragile on this kernel
