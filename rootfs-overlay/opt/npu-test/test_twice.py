#!/usr/bin/env python3
"""
THE CLEANEST WALL EXPERIMENT: run ONE KNOWN-GOOD conv N times in a row, in one
power session, and compare every invoke against the CPU reference.

Why this and not a chained model. Everything used to study the wall so far has
varied two things at once: chained models run DIFFERENT layers, so "op1 is
wrong" could be the position or could be that layer. conv2x turned out to have
a broken op0 as well (core[dt_wr]=16 where 25600 was due), so it cannot serve
as a baseline either. conv2d-cal, by contrast, is byte-exact against the relu
reference (exact=100.0%, 2026-07-26 and back to 2026-06-27).

So: same op, same config, same buffers, same everything -- the ONLY difference
between invoke 0 and invoke 1 is that one of them is second. If invoke 1 is
wrong, the wall is purely positional and this is the minimal repro we have been
missing. If invoke 1 is RIGHT, then the wall is not "the second op fails" at
all, it is something about running a DIFFERENT op, and a large part of the
ledger needs rereading.

Either answer is worth the run, and neither has been measured.

The oracle is the same one test_conv.py uses: the hardware applies a ReLU at
the output zero point, so the reference is max(CPU, out_zp), not raw CPU.

Usage: TEFLON_LIB=/usr/lib/libteflon.so python3 test_twice.py <model> [N]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 6

det = tflite.Interpreter(model_path=model)
det.allocate_tensors()
ishape = det.get_input_details()[0]["shape"]
n = int(np.prod(ishape))
indata = (np.arange(n) % 251).astype(np.int64)

print(f"=== {os.path.basename(model)} x{reps} in one session ===", flush=True)


def build(use_npu):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})] if use_npu else []
    it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    it.allocate_tensors()
    return it


def invoke(it):
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    it.invoke()
    return it.get_tensor(out["index"])[0].flatten().astype(int)


# CPU reference first, so the NPU session below is uninterrupted.
cpu = invoke(build(False))

# One interpreter, one delegate, N invokes -- no teardown in between, so the
# NPU stays powered and every invoke after the first is a "later op".
it_npu = build(True)
runs = [invoke(it_npu) for _ in range(reps)]

# Output zero point from the MODEL, not guessed from the data. Guessing it with
# bincount gave 126 instead of 128 on conv2d-cal, which made every invoke read
# as WRONG (maxdiff=2, exact=50.3%) when test_conv.py scores the same tensor
# exact=100.0%. The oracle has to come from the quantisation params.
_oq = det.get_output_details()[0].get("quantization", (0.0, 0))
zp = int(_oq[1]) if _oq and len(_oq) > 1 else 128
ref = np.maximum(cpu, zp)                             # hardware relu's the accumulator

print(f"  CPU: distinct={len(np.unique(cpu))} mean={cpu.mean():.1f}  (zp guess {zp})", flush=True)
verdicts = []
for i, npu in enumerate(runs):
    md = int(np.abs(npu - ref).max())
    exact = float((npu == ref).mean() * 100)
    ok = md <= 2
    verdicts.append(ok)
    print(f"  invoke {i}: distinct={len(np.unique(npu)):3d} mean={npu.mean():6.1f} "
          f"| vs RELU-ref maxdiff={md:3d} exact={exact:5.1f}%  {'OK' if ok else 'WRONG'}",
          flush=True)

if all(verdicts):
    print("  VERDICT: every invoke correct -- the wall is NOT positional. Running the")
    print("           same op again does re-arm. The wall needs a DIFFERENT op.", flush=True)
elif verdicts[0] and not any(verdicts[1:]):
    print("  VERDICT: invoke 0 correct, all later ones wrong -- the wall is PURELY")
    print("           POSITIONAL. Same op, same config, same buffers. Minimal repro.", flush=True)
else:
    first_bad = next((i for i, v in enumerate(verdicts) if not v), None)
    print(f"  VERDICT: mixed {verdicts} -- first bad invoke = {first_bad}. Repeats of")
    print("           the SAME op survive up to there, so whatever fails is not")
    print("           simply 'being the second op'.", flush=True)

sys.stdout.flush()
os._exit(0)          # skip interpreter GC; BO teardown is fragile on this kernel
