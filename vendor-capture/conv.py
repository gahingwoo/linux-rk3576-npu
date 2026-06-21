#!/usr/bin/env python3
"""
Convert work/<tag>.onnx -> work/<tag>.rknn for rk3576, quietly.
Usage: conv.py <tag>
"""
import sys, os, contextlib
from rknn.api import RKNN

tag = sys.argv[1]
onnx = f"work/{tag}.onnx"
out = f"work/{tag}.rknn"

rknn = RKNN(verbose=False)
rknn.config(target_platform="rk3576")
if rknn.load_onnx(model=onnx) != 0:
    print("load_onnx failed"); sys.exit(1)
if rknn.build(do_quantization=True, dataset=f"work/{tag}.txt") != 0:
    print("build failed"); sys.exit(1)
if rknn.export_rknn(out) != 0:
    print("export failed"); sys.exit(1)
rknn.release()
print("OK", out)
