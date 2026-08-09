# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
import sys
from rknn.api import RKNN
rknn = RKNN(verbose=False)
rknn.config(target_platform="rk3576")
if rknn.load_onnx(model="work/fck.onnx") != 0: print("load fail"); sys.exit(1)
if rknn.build(do_quantization=True, dataset="work/fck.txt") != 0: print("build fail"); sys.exit(1)
if rknn.export_rknn("work/fck.rknn") != 0: print("export fail"); sys.exit(1)
print("OK wrote work/fck.rknn")
rknn.release()
