#!/usr/bin/env python3
"""
Does the depthwise CMAC read its weight buffer at all?

mesa carries ROCKET_DW_WTEST, which overwrites the entire depthwise weight
buffer with 0x7f. It was written in June, when only the first submit after a
reset computed anything, so "the output is zero" could not be told apart from
"the buffer was never written". With the TASK_CON fix that ambiguity is gone and
the test finally means something.

Run this twice, once plain and once with ROCKET_DW_WTEST=1 in the environment,
and compare the output bytes:

  outputs DIFFER    the CMAC does read the weight buffer, so the real-weight
                    failure is the LAYOUT: the weights land in lanes it ignores
  outputs IDENTICAL the CMAC reads nothing from that buffer, and the problem is
                    upstream of the weights, in staging or the depthwise mode

The plain run also reports how far it is from the CPU reference, using
max(cpu, zp) because the hardware ReLUs at the output zero point.

Usage: TEFLON_LIB=... [ROCKET_DW_WTEST=1] python3 test_dw.py <model.tflite>
"""
import hashlib
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
tag = "WTEST(all weights 0x7f)" if os.environ.get("ROCKET_DW_WTEST") else "plain"

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
n = int(np.prod(ci["shape"]))
data = ((np.arange(n) * 7) % 251).astype(np.int64)

cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
ref = cpu.get_tensor(co["index"]).flatten().astype(int)
oq = co.get("quantization", (0.0, 0))
zp = int(oq[1]) if oq and len(oq) > 1 else 0

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"]).flatten().astype(int)

h = hashlib.md5(got.astype(np.uint8).tobytes()).hexdigest()[:12]
print(f"  {os.path.basename(model)} {tag}: distinct={len(np.unique(got)):3d} "
      f"mean={got.mean():7.2f} min={got.min():3d} max={got.max():3d} md5={h}", flush=True)
print(f"    vs CPU: raw maxdiff={int(np.abs(got - ref).max()):3d} "
      f"relu maxdiff={int(np.abs(got - np.maximum(ref, zp)).max()):3d}  "
      f"(zp={zp})", flush=True)

sys.stdout.flush()
os._exit(0)
