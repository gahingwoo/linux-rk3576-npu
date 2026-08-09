#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Run a model on the NPU and print the first N output values.

Why: cal_k3 and cal_k1 fail with output that VARIES with the input, unlike the
md003 family which returns a flat out_zp. A varying wrong answer is a computed
answer, so the actual numbers are worth something: with the input generated
deterministically, a handful of output values is enough to test candidate weight
orderings offline on the host and see which one the hardware actually used.

Usage: TEFLON_LIB=... head.py <model.tflite> [count]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
count = int(sys.argv[2]) if len(sys.argv) > 2 else 64

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]

n = int(np.prod(ni["shape"]))
data = ((np.arange(n) * 7) % 251).astype(np.int64)
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"]).flatten().astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
ref = cpu.get_tensor(co["index"]).flatten().astype(int)

print(f"  {os.path.basename(model)} input (arange*7)%251, out{list(no['shape'])}",
      flush=True)
print("  npu:", " ".join(f"{v:3d}" for v in got[:count]), flush=True)
print("  cpu:", " ".join(f"{v:3d}" for v in ref[:count]), flush=True)
sys.stdout.flush()
os._exit(0)
