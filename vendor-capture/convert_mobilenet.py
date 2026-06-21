#!/usr/bin/env python3
"""
Convert the real (already-quantized) MobileNetV1 tflite to an RK3576 .rknn so the
vendor driver compiles the real per-layer register command stream. We diff the
captured per-task regcmd (conv0/dw1/pw1/...) against mesa layer by layer.
do_quantization=False: keep the tflite's own int8 quant params (so each layer's
OUT_CVT matches the real model, unlike a re-quantized synthetic conv).
"""
import sys
from rknn.api import RKNN

TFL = "../rootfs-overlay/opt/npu-test/mobilenet_v1_1.0_224_quant.tflite"
OUT = "mobilenet_rk3576.rknn"

rknn = RKNN(verbose=True)
rknn.config(target_platform="rk3576")

print("== load_tflite ==")
if rknn.load_tflite(model=TFL) != 0:
    print("load_tflite failed"); sys.exit(1)

print("== build (no requant; keep tflite int8 params) ==")
if rknn.build(do_quantization=False) != 0:
    print("build failed"); sys.exit(1)

print("== export_rknn ==")
if rknn.export_rknn(OUT) != 0:
    print("export failed"); sys.exit(1)

print("OK wrote", OUT)
rknn.release()
