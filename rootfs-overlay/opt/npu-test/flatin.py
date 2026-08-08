#!/usr/bin/env python3
"""
Feed a constant input at exactly the input zero point and report the output.

This is the simplest failing test this project has. The hardware MAC computes
sum((in - 0x80) * w_stored), so an input of exactly 0x80 makes every product
zero and the answer must be requant(bias), whatever the kernel is. cal_k3 and
cal_k1 are conv2d-cal with the kernel cropped, so all three carry the SAME bias
and the SAME requant, confirmed by every log line reading shift=25 scale=0x7d34.
The answer therefore has to be identical for all three, and it is not.

No input data, no spatial mapping, no weights worth speaking of: just bias
through the requant. Anything that differs here is upstream of everything else.

Usage: TEFLON_LIB=... flatin.py <model.tflite>
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
in_zp = int(ni["quantization"][1])
flat = np.full(list(ni["shape"]), in_zp, dtype=ni["dtype"])
npu.set_tensor(ni["index"], flat)
npu.invoke()
got = npu.get_tensor(no["index"])[0].astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], flat)
cpu.invoke()
ref = cpu.get_tensor(co["index"])[0].astype(int)
zp = int(co["quantization"][1])

# every output pixel should be the same, so channel 0 row 0 tells the story
print(f"  {os.path.basename(model)} in_zp={in_zp} out_zp={zp}", flush=True)
print(f"    npu distinct={len(np.unique(got)):4d} min={got.min():3d} max={got.max():3d} "
      f"first 12 ch: {list(got[0, 0, :12])}", flush=True)
print(f"    cpu distinct={len(np.unique(ref)):4d} min={ref.min():3d} max={ref.max():3d} "
      f"first 12 ch: {list(ref[0, 0, :12])}", flush=True)
print(f"    spatially uniform on npu? {bool((got == got[0, 0]).all())}", flush=True)
sys.stdout.flush()
os._exit(0)
