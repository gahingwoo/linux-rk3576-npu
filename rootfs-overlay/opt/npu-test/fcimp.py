#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Decode a first-conv impulse run: say which INPUT PLANE and which tap the
hardware used for each output channel.

fc_imp.tflite is mn_conv0 with one live tap per output channel, at input
channel c mod 3 and tap (c / 3) mod 9, everything else at the weight zero point
and a zero bias. conv0 is stride 2 with SAME padding, so the correct output is

    out[y][x][c] = in[2y + ky - 1][2x + kx - 1][c mod 3] * w

and reading back which plane and which (ky, kx) actually fits names the input
layout. The CPU interpreter runs the same file and is decoded the same way, as
the control: if its own answer is not the identity mapping then the model is
not what this script thinks it is and the hardware column means nothing.

Usage: TEFLON_LIB=... fcimp.py [model.tflite]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

model = sys.argv[1] if len(sys.argv) > 1 else "/opt/npu-test/fc_imp.tflite"
teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
npu = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
npu.allocate_tensors()
ni, no = npu.get_input_details()[0], npu.get_output_details()[0]
n_in = int(np.prod(ni["shape"]))
data = ((np.arange(n_in) * 7) % 251).astype(np.int64)
npu.set_tensor(ni["index"], data.astype(ni["dtype"]).reshape(ni["shape"]))
npu.invoke()
got = npu.get_tensor(no["index"])[0].astype(int)

cpu = tflite.Interpreter(model_path=model)
cpu.allocate_tensors()
ci, co = cpu.get_input_details()[0], cpu.get_output_details()[0]
cpu.set_tensor(ci["index"], data.astype(ci["dtype"]).reshape(ci["shape"]))
cpu.invoke()
ref = cpu.get_tensor(co["index"])[0].astype(int)

x = data.reshape(ni["shape"])[0].astype(int)
IH, IW, IC = x.shape
OH, OW, OC = got.shape
S = IH // OH


def tapped(plane, ky, kx):
    """The stride-2 view of a plane that the tap at (ky, kx) sees."""
    out = np.zeros((OH, OW), dtype=np.int64)
    for y in range(OH):
        sy = S * y + ky - 1
        if not (0 <= sy < IH):
            continue
        xs = S * np.arange(OW) + kx - 1
        ok = (xs >= 0) & (xs < IW)
        out[y, ok] = plane[sy, xs[ok]]
    return out


# A crop away from the border, where padding cannot confuse the fit.
sl = (slice(8, 40), slice(8, 40))
CAND = [(p, ky, kx) for p in range(IC) for ky in range(3) for kx in range(3)]
VIEWS = {(p, ky, kx): tapped(x[:, :, p], ky, kx)[sl].ravel().astype(float)
         for (p, ky, kx) in CAND}


def decode(surface):
    v = surface[sl].ravel().astype(float)
    if v.std() == 0:
        return (0.0, None)
    best = (-2.0, None)
    for k, cand in VIEWS.items():
        if cand.std() == 0:
            continue
        r = float(np.corrcoef(v, cand)[0, 1])
        if r > best[0]:
            best = (r, k)
    return best


print(f"  {os.path.basename(model)} out{got.shape} in{x.shape} stride {S}")
print(f"  npu distinct={len(np.unique(got))}  cpu distinct={len(np.unique(ref))}")

hits_cpu = hits_npu = plane_ok = 0
rows = []
for c in range(OC):
    want = (c % IC, ((c // IC) % 9) // 3, ((c // IC) % 9) % 3)
    rc, gc = decode(ref[:, :, c]), decode(got[:, :, c])
    hits_cpu += rc[1] == want
    hits_npu += gc[1] == want
    if gc[1] is not None and gc[1][0] == want[0]:
        plane_ok += 1
    rows.append((c, want, rc, gc))

print(f"  CONTROL, the CPU decodes to its own impulse: {hits_cpu}/{OC}")
print(f"  hardware decodes to the same impulse:        {hits_npu}/{OC}")
print(f"  hardware reads the RIGHT INPUT PLANE:        {plane_ok}/{OC}")
ph = {}
for c, want, rc, gc in rows:
    k = None if gc[1] is None else (gc[1][0] - want[0]) % IC
    ph[k] = ph.get(k, 0) + 1
print("  plane offset (npu plane - wanted) counts: "
      + ", ".join(f"{'dead' if k is None else k}:{n}" for k, n in sorted(
          ph.items(), key=lambda kv: (kv[0] is None, kv[0]))))
print("  ch  want (ic,ky,kx)   cpu says        npu says        corr")
for c, want, rc, gc in rows[:16]:
    print(f"  {c:3d} {str(want):15s} {str(rc[1]):15s} {str(gc[1]):15s} "
          f"{gc[0]:+.3f}")
sys.stdout.flush()
os._exit(0)
