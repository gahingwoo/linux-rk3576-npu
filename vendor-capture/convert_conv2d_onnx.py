import sys
from rknn.api import RKNN
rknn = RKNN(verbose=True)
rknn.config(target_platform="rk3576")
if rknn.load_onnx(model="conv2d.onnx") != 0: print("load fail"); sys.exit(1)
if rknn.build(do_quantization=True, dataset="work/conv2d_ds.txt") != 0: print("build fail"); sys.exit(1)
if rknn.export_rknn("conv2d_rk3576.rknn") != 0: print("export fail"); sys.exit(1)
print("OK wrote conv2d_rk3576.rknn")
rknn.release()
