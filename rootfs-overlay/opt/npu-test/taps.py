#!/usr/bin/env python3
"""
With an impulse kernel, work out which input pixel the hardware paired each
kernel tap with.

mutate_impulse.py gives output channel c a single live tap at (c/k, c%k), so a
correct convolution makes channel c a copy of the input shifted by that tap. If
the hardware used a different tap than the one the weights encode, then NPU
channel c will match the CPU's channel c' instead, where c' is the channel whose
tap is the one actually used. So recovering, for each NPU channel, which CPU
channel it equals recovers the tap mapping directly, in units of taps.

The hardware ReLUs at the output zero point, so the comparison is against
max(cpu, zp), the same reference test_model.py uses.

Prints for each of the first k*k channels: the best matching CPU channel and how
well it matches. A clean identity mapping means the pairing is right and the
cancellation is somewhere else; a permutation is the bug, named exactly.

Usage: TEFLON_LIB=... taps.py <model.tflite> <k>
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model, K = sys.argv[1], int(sys.argv[2])

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
n = int(np.prod(ni["shape"]))
data = ((np.arange(n) * 7) % 251).astype(np.int64)
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"])[0].astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
ref = cpu.get_tensor(co["index"])[0].astype(int)

zp = int(co["quantization"][1])
ref = np.maximum(ref, zp)
taps = K * K
print(f"  {os.path.basename(model)} out{got.shape} zp={zp}, {taps} live taps", flush=True)
print(f"  npu distinct={len(np.unique(got))} min={got.min()} max={got.max()}   "
      f"cpu distinct={len(np.unique(ref))} min={ref.min()} max={ref.max()}", flush=True)

# ⚠ A flat NPU surface makes every "best match" meaningless: a constant equal to
# the zero point agrees with the reference wherever the reference is below it,
# which reads as a high percentage for whichever channel is most often low. The
# first version of this probe did exactly that, and its control caught it.
if len(np.unique(got)) <= 2:
    print("  VOID: the NPU output is flat, no mapping can be read from it",
          flush=True)
    sys.stdout.flush()
    os._exit(0)

for c in range(min(taps, got.shape[2])):
    scores = []
    for c2 in range(min(taps, ref.shape[2])):
        same = float((got[:, :, c] == ref[:, :, c2]).mean())
        scores.append((same, c2))
    scores.sort(reverse=True)
    best, bc = scores[0]
    ky, kx = c // K, c % K
    by, bx = bc // K, bc % K
    mark = "ok" if bc == c and best > 0.98 else ""
    print(f"    ch{c:2d} tap({ky},{kx}): best match cpu ch{bc:2d} tap({by},{bx}) "
          f"at {100*best:5.1f}%   self {100*scores[[s[1] for s in scores].index(c)][0]:5.1f}%  {mark}",
          flush=True)

sys.stdout.flush()
os._exit(0)
