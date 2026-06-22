import sys
from rknn.api import RKNN
onnx, ds, out = sys.argv[1], sys.argv[2], sys.argv[3]
r = RKNN(verbose=False)
r.config(target_platform="rk3576", quantized_method="layer")   # per-TENSOR, matches conv2d.tflite
assert r.load_onnx(model=onnx) == 0, "load fail"
assert r.build(do_quantization=True, dataset=ds) == 0, "build fail"
assert r.export_rknn(out) == 0, "export fail"
print("OK", out); r.release()
