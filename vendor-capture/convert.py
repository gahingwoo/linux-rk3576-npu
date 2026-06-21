#!/usr/bin/env python3
"""
Convert the single-conv ONNX to an RK3576 .rknn. The toolkit compiles the NPU
register command stream for rk3576 into the .rknn — the vendor's known-good CNA
arm/start sequence we want to diff against mesa's regcmd. verbose=True to capture
anything the toolkit prints.
"""
import sys
from rknn.api import RKNN

ONNX = "conv0.onnx"
OUT = "conv0_rk3576.rknn"

rknn = RKNN(verbose=True)
rknn.config(target_platform="rk3576")

print("== load_onnx ==")
if rknn.load_onnx(model=ONNX) != 0:
    print("load_onnx failed"); sys.exit(1)

print("== build ==")
if rknn.build(do_quantization=True, dataset="dataset.txt") != 0:
    print("build failed"); sys.exit(1)

print("== export_rknn ==")
if rknn.export_rknn(OUT) != 0:
    print("export failed"); sys.exit(1)

print("OK wrote", OUT)
rknn.release()
