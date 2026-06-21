#!/usr/bin/env python3
"""
Tomeu's isolation method: run a SINGLE-op tflite on the NPU (Teflon) and on the
CPU with the SAME known input, and compare the outputs. If the NPU output is
degenerate (all one value) while the CPU output is a real feature map, the op is
broken in isolation -- which separates a per-op pipeline bug from a whole-graph
/ chaining bug.

Usage: TEFLON_LIB=/usr/lib/libteflon.so python3 test_conv.py <model.tflite>
"""
import os, sys
import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]


def run(use_npu, indata):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})] if use_npu else []
    it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    it.allocate_tensors()
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    it.invoke()
    return it.get_tensor(out["index"])[0], inp, out


# Known, structured input (a byte ramp) so both backends get the identical data.
det = tflite.Interpreter(model_path=model)
det.allocate_tensors()
ishape = det.get_input_details()[0]["shape"]
n = int(np.prod(ishape))
indata = (np.arange(n) % 251).astype(np.int64)

npu, inp, out = run(True, indata)
cpu, _, _ = run(False, indata)


def desc(a):
    f = a.flatten().astype(int)
    return (f"distinct={len(np.unique(f))} nonzero={np.count_nonzero(f)}/{f.size} "
            f"min={f.min()} max={f.max()} first16={f[:16].tolist()}")


print(f"=== {os.path.basename(model)}  in{list(inp['shape'])} {inp['dtype'].__name__} "
      f"-> out{list(out['shape'])} ===")
print(f"  NPU: {desc(npu)}")
print(f"  CPU: {desc(cpu)}")
if npu.shape == cpu.shape:
    md = int(np.max(np.abs(npu.astype(int) - cpu.astype(int))))
    same = bool(np.array_equal(npu, cpu))
    print(f"  RESULT: match={same}  maxdiff={md}  "
          f"NPU_distinct={len(np.unique(npu))} ({'DEGENERATE/BROKEN' if len(np.unique(npu)) <= 2 else 'computes'})")
else:
    print(f"  RESULT: shape mismatch NPU{list(npu.shape)} CPU{list(cpu.shape)}")
