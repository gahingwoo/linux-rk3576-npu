#!/usr/bin/env python3
"""
Recover the order the vendor stores a kernel's spatial planes in, and validate
the method on a kernel size that is known to work before trusting it on one that
is not.

The first attempt at this gave every weight a value depending only on (ky, kx),
which makes the tensor rank one and lets the toolkit restructure it, and it
identified each block from a single byte, which stops meaning anything the
moment the weights carry any variation. Its output was recorded as unsafe rather
than as a finding.

This gives plane p a distinct value BAND instead: a centre far enough from its
neighbours that per (oc, ic) variation inside the band cannot be confused with
another plane. So every byte still names its plane, and the tensor is ordinary.

The validation matters more than the result. mesa packs the generic weight buffer
as [oc/32][ic/32][kx][ky][oc%32][ic%32], and 5x5 computes correctly with that
order, so a probe that cannot recover exactly that order for 5x5 is not measuring
what it claims to. Only if the 5x5 case comes back as mesa's own nesting is the
3x3 answer worth anything.

Usage: posprobe_planes.py [k] [ic] [oc]
"""
import os
import sys

import numpy as np
import torch
import torch.nn as nn

K = int(sys.argv[1]) if len(sys.argv) > 1 else 5
IC = int(sys.argv[2]) if len(sys.argv) > 2 else 16
OC = int(sys.argv[3]) if len(sys.argv) > 3 else 16
HW = 80
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geom")
os.makedirs(OUT, exist_ok=True)

# Plane centres spread over the int8 range, with room for jitter between them.
span = 220.0 / max(K * K - 1, 1)
centres = np.array([-110.0 + p * span for p in range(K * K)]).reshape(K, K)
rng = np.random.RandomState(0)
jitter = rng.uniform(-span / 5, span / 5, size=(OC, IC, 1, 1))
w = (np.broadcast_to(centres, (OC, IC, K, K)) + jitter).astype(np.float32)

m = nn.Conv2d(IC, OC, K, padding=K // 2, bias=True)
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w))
    m.bias.zero_()
m.eval()

name = f"pp_p{K}"
onnx = f"{OUT}/{name}.onnx"
torch.onnx.export(m, torch.randn(1, IC, HW, HW), onnx,
                  input_names=["input"], output_names=["output"], opset_version=12)
calib = f"{OUT}/{name}_c.npy"
np.save(calib, (np.arange(IC * HW * HW).reshape(1, IC, HW, HW) % 251).astype(np.uint8))
ds = f"{OUT}/{name}_d.txt"
open(ds, "w").write(os.path.abspath(calib) + "\n")

from rknn.api import RKNN
r = RKNN(verbose=False)
r.config(target_platform="rk3576", quantized_method="layer", compress_weight=False)
assert r.load_onnx(model=onnx) == 0
assert r.build(do_quantization=True, dataset=ds) == 0
rk = f"{OUT}/{name}_rk3576.rknn"
assert r.export_rknn(rk) == 0
r.release()

# Predict the quantized band each plane lands in, using the quantizer's own rule.
scale = float(np.abs(w).max()) / 127.0
qc = np.round(centres / scale).astype(int).flatten()
# band half width has to exceed the per (oc, ic) jitter or a plane stops being
# one run; the run-length filter below is what rejects false positives
half = int(round(span / scale / 2)) - 1
print(f"k={K}: plane centres after quantization {list(qc)}, half width {half}")


def band(b):
    v = b - 256 if b > 127 else b
    for p, c in enumerate(qc):
        if abs(v - c) <= half:
            return p
    return None


data = open(rk, "rb").read()
bands = [band(b) for b in data]

# Longest region made of long same-band runs: that is the weight buffer.
runs = []
i = 0
while i < len(bands):
    j = i
    while j < len(bands) and bands[j] == bands[i]:
        j += 1
    runs.append((i, bands[i], j - i))
    i = j
# A plane is oc*ic bytes when both fit one atom, so look for runs of exactly
# that length rather than guessing at clusters.
PLANE = OC * IC
seq = [r for r in runs if r[1] is not None and r[2] == PLANE]
if not seq:
    print(f"no runs of exactly {PLANE} bytes found")
    sys.exit(1)
print(f"{len(seq)} runs of exactly {PLANE} bytes, first at 0x{seq[0][0]:06x}")
gaps = {seq[i+1][0] - seq[i][0] for i in range(len(seq)-1)}
print(f"  stride between them: {sorted(gaps)}")
print(f"  plane order as stored: {[s[1] for s in seq]}")

expect = [x * K + y for x in range(K) for y in range(K)]
got = [s[1] for s in seq]
print(f"  mesa's nesting [kx][ky] would be: {expect}")
print(f"  MATCHES MESA: {got[:len(expect)] == expect}")
