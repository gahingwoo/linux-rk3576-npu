#!/usr/bin/env python3
"""
Convert Mesa's own conv2d.tflite to an RK3576 .rknn, keeping the tflite's
quantized weights byte-for-byte (do_quantization=False). This guarantees the
vendor stack and Mesa run the IDENTICAL conv with the IDENTICAL int8 weights,
so the BO dumps can be diffed without worrying whether the two models match.
"""
import sys
from rknn.api import RKNN

TFLITE = sys.argv[1] if len(sys.argv) > 1 else "conv2d.tflite"
OUT = sys.argv[2] if len(sys.argv) > 2 else "conv2d_rk3576.rknn"

rknn = RKNN(verbose=True)
rknn.config(target_platform="rk3576")

print("== load_tflite ==", TFLITE)
if rknn.load_tflite(model=TFLITE) != 0:
    print("load_tflite failed"); sys.exit(1)

print("== build (do_quantization=False -> keep tflite int8 weights) ==")
if rknn.build(do_quantization=False) != 0:
    print("build failed"); sys.exit(1)

print("== export_rknn ==", OUT)
if rknn.export_rknn(OUT) != 0:
    print("export failed"); sys.exit(1)

print("OK wrote", OUT)
rknn.release()
