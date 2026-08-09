#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Put the impulse in the INPUT, not the kernel, and see where the output responds.

The impulse-kernel probe was badly conditioned and returned a flat surface even
at the kernel size that computes correctly. It needed 399 taps sitting exactly at
the weight zero point to cancel against one live tap, and mesa stores weights as
`w - 0x80` with the B operand doing that correction, so the signal was a four
hundredth of a large cancellation. Scaling the output did not save it.

An input impulse has none of that. The kernel stays the real, well conditioned
one from a model that computes; only the input changes. Feed the input zero
point everywhere, then feed it again with a single pixel raised, and subtract.
The response is the kernel footprint, and where it lands says which output
pixels that input pixel reached:

    out[y][x] responds iff  stride*y + ky - pad_top == y0  for some tap ky

So the footprint's position and extent name the tap-to-pixel mapping directly,
and the same measurement on the kernel size that works gives the reference for
what a correct footprint looks like.

Usage: TEFLON_LIB=... impulse_in.py <model.tflite> [y0] [x0]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
y0 = int(sys.argv[2]) if len(sys.argv) > 2 else 20
x0 = int(sys.argv[3]) if len(sys.argv) > 3 else 20


def run(interp, idx, data):
    interp.set_tensor(idx, data)
    interp.invoke()
    return interp.get_tensor(out_idx).astype(int)


deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
in_idx, out_idx = ni["index"], no["index"]
in_zp = int(ni["quantization"][1])
shape = list(ni["shape"])

flat = np.full(shape, in_zp, dtype=ni["dtype"])
delta = flat.copy()
delta[0, y0, x0, :] = 255

base_n = run(npu, in_idx, flat)
resp_n = run(npu, in_idx, delta)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
out_idx = co["index"]
base_c = run(cpu, ci["index"], flat)
resp_c = run(cpu, ci["index"], delta)


def footprint(base, resp, who):
    d = np.abs(resp - base)[0].sum(axis=2)
    ys, xs = np.nonzero(d)
    print(f"  {who}: baseline distinct={len(np.unique(base))} "
          f"response nonzero at {len(ys)} positions", flush=True)
    if len(ys) == 0:
        print(f"    no response anywhere, nothing to read", flush=True)
        return
    print(f"    rows {ys.min()}..{ys.max()}  cols {xs.min()}..{xs.max()}", flush=True)
    for y in range(ys.min(), min(ys.max() + 1, ys.min() + 6)):
        row = " ".join(f"{int(d[y, x]):5d}"
                       for x in range(xs.min(), min(xs.max() + 1, xs.min() + 6)))
        print(f"      y={y:3d}: {row}", flush=True)


print(f"  {os.path.basename(model)} in{shape} in_zp={in_zp}, impulse at "
      f"({y0},{x0}) all channels", flush=True)
footprint(base_c, resp_c, "cpu")
footprint(base_n, resp_n, "npu")

sys.stdout.flush()
os._exit(0)
