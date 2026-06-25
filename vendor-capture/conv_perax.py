import sys, numpy as np
from rknn.api import RKNN
ONNX="/home/parallels/Desktop/linux-rk3576-npu/vendor-capture/conv2d.onnx"
OUT=sys.argv[1]
# fresh NCHW calib matching the onnx input [1,16,80,80]
calib=(np.arange(1*16*80*80)%251).astype(np.float32).reshape(1,16,80,80)
np.save("/tmp/perax_calib.npy", calib)
open("/tmp/perax_ds.txt","w").write("/tmp/perax_calib.npy\n")
r=RKNN(verbose=False)
r.config(target_platform="rk3576", quantized_dtype="w8a8", quantized_method="channel")
assert r.load_onnx(model=ONNX)==0, "load_onnx failed"
assert r.build(do_quantization=True, dataset="/tmp/perax_ds.txt")==0, "build failed"
assert r.export_rknn(OUT)==0, "export failed"
print("OK wrote", OUT)
r.release()
