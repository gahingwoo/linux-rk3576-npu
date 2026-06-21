#!/usr/bin/env python3
"""
Compare the ORIGINAL conv weights (from the tflite) against what Mesa actually
encoded (the ROCKET_DEBUG=dump_bos mesa-weights-*.bin). If Mesa's encoded weights
are degenerate (all one value / zero) while the original is varied, the
coefficients BO is the bug. If both are varied, the encoding is fine and the bug
is downstream (staging / a kernel write).

Usage: analyze_dump.py <model.tflite> <dumpdir>
"""
import sys, os, glob
import numpy as np
import tflite_runtime.interpreter as tflite

model, dumpdir = sys.argv[1], sys.argv[2]


def stat(a):
    f = a.flatten().astype(int)
    return f"{f.size}B distinct={len(np.unique(f))} nz={np.count_nonzero(f)} min={f.min()} max={f.max()} head={f[:16].tolist()}"


print("--- ORIGINAL tflite constant tensors (weights/bias) ---")
it = tflite.Interpreter(model_path=model)
it.allocate_tensors()
for d in it.get_tensor_details():
    try:
        t = it.get_tensor(d["index"])
    except Exception:
        continue
    if t.ndim == 4 and t.size > 16:          # conv weights
        print(f"  [{d['index']}] {d['name'][:34]:34} shape{list(t.shape)} {t.dtype}: {stat(t)}")
    elif t.ndim == 1 and 4 <= t.size <= 4096 and 'bias' in (d['name'] or '').lower():
        print(f"  [{d['index']}] {d['name'][:34]:34} shape{list(t.shape)} {t.dtype}: {stat(t)}")

print("--- MESA encoded buffers (ROCKET_DEBUG=dump_bos) ---")
files = sorted(glob.glob(os.path.join(dumpdir, "mesa-*.bin")))
if not files:
    print("  (no mesa-*.bin dumped — ROCKET_DEBUG=dump_bos not active?)")
for f in files:
    b = np.fromfile(f, dtype=np.uint8)
    print(f"  {os.path.basename(f):28}: {stat(b)}")
