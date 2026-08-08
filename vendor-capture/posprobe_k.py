#!/usr/bin/env python3
"""
Where does the vendor put each SPATIAL PLANE of a k>1 kernel?

mesa packs the generic (non pointwise, non first conv) weight buffer as
[oc/32][ic/32][kx][ky][oc%32][ic%32], so for 16 in and 16 out channels that is
nine contiguous 256 byte planes, one per (kx, ky), each holding oc-major and
ic-contiguous bytes. 5x5 computes correctly with that order and 3x3 does not,
which is only possible if something about the order is size dependent, so read
the vendor's own answer instead of assuming.

Give every weight a value that depends ONLY on (ky, kx). Then each plane is a
single repeated byte and the layout falls out of where the runs are, with no
need to make 2304 positions individually distinct.

Usage: posprobe_k.py [k] [ic] [oc]
"""
import os, sys
import numpy as np, torch, torch.nn as nn

K  = int(sys.argv[1]) if len(sys.argv) > 1 else 3
IC = int(sys.argv[2]) if len(sys.argv) > 2 else 16
OC = int(sys.argv[3]) if len(sys.argv) > 3 else 16
HW = 80
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geom")
os.makedirs(OUT, exist_ok=True)

# value depends only on the spatial position, well separated after quantisation
plane = (np.arange(K * K).reshape(K, K) + 1) / float(K * K)
w = np.broadcast_to(plane, (OC, IC, K, K)).copy().astype(np.float32)

m = nn.Conv2d(IC, OC, K, padding=K // 2, bias=True)
with torch.no_grad():
    m.weight.copy_(torch.from_numpy(w)); m.bias.zero_()
m.eval()
onnx = f"{OUT}/pp_k{K}.onnx"
torch.onnx.export(m, torch.randn(1, IC, HW, HW), onnx,
                  input_names=["input"], output_names=["output"], opset_version=12)
calib = f"{OUT}/pp_k{K}_c.npy"
np.save(calib, (np.arange(IC*HW*HW).reshape(1, IC, HW, HW) % 251).astype(np.uint8))
ds = f"{OUT}/pp_k{K}_d.txt"; open(ds, "w").write(os.path.abspath(calib) + "\n")

from rknn.api import RKNN
r = RKNN(verbose=False); r.config(target_platform="rk3576", quantized_method="layer")
assert r.load_onnx(model=onnx) == 0
assert r.build(do_quantization=True, dataset=ds) == 0
rk = f"{OUT}/pp_k{K}_rk3576.rknn"; assert r.export_rknn(rk) == 0; r.release()

scale = float(np.abs(w).max()) / 127.0
q = [int(round(float(v) / scale)) & 0xff for v in plane.flatten()]
print(f"k={K}: the {K*K} plane bytes, in (ky,kx) order: {q}")

data = open(rk, "rb").read()
need = OC * IC * K * K
best, bestscore = None, -1
for off in range(len(data) - need):
    blk = data[off:off+need]
    if blk[0] not in q:
        continue
    runs, i = [], 0
    while i < need:
        j = i
        while j < need and blk[j] == blk[i]:
            j += 1
        runs.append((blk[i], j - i)); i = j
    score = sum(l for v, l in runs if v in q and l >= 64)
    if score > bestscore:
        bestscore, best = score, (off, runs)
off, runs = best
print(f"blob at 0x{off:x}, {need} bytes, {len(runs)} runs, {bestscore} bytes in long same-value runs")
print("  runs (value, length), first 16:")
for v, l in runs[:16]:
    where = q.index(v) if v in q else None
    tag = f"plane (ky={where//K},kx={where%K})" if where is not None else "?"
    print(f"    0x{v:02x} x{l:5d}   {tag}")
