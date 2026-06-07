#!/usr/bin/env python3
"""
Teflon MobileNetV1 UINT8 inference for RK3576 NPU bringup.
Usage: TEFLON_LIB=/usr/lib/libteflon.so python3 infer.py <model.tflite> [image]
Exit: 0=ok  1=runtime error  2=tflite_runtime/numpy missing
"""
import os, sys, time


def die(msg, code=1):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(code)


teflon_lib = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_path = sys.argv[1] if len(sys.argv) > 1 else die("usage: infer.py <model.tflite> [image]")
img_path   = sys.argv[2] if len(sys.argv) > 2 else None

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    die("tflite_runtime missing — run: pip3 install tflite-runtime==2.14.0", code=2)

try:
    import numpy as np
except ImportError:
    die("numpy missing — run: pip3 install numpy", code=2)

print(f"Teflon:  {teflon_lib}")
print(f"Model:   {model_path}")

interp = tflite.Interpreter(
    model_path=model_path,
    experimental_delegates=[tflite.load_delegate(
        teflon_lib,
        options={"TEFLON_DEBUG": os.environ.get("TEFLON_DEBUG", "0")},
    )],
)
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]
print(f"Input:   {inp['shape']}  dtype={inp['dtype'].__name__}")

if img_path and os.path.exists(img_path):
    try:
        from PIL import Image
        data = np.array(
            Image.open(img_path).resize((224, 224)).convert("RGB"), dtype=np.uint8
        )[np.newaxis]
        print(f"Image:   {img_path}")
    except Exception:
        print("Image:   random (PIL load failed)")
        data = np.random.randint(0, 256, inp["shape"], dtype=np.uint8)
else:
    print("Image:   random (no image provided)")
    data = np.random.randint(0, 256, inp["shape"], dtype=np.uint8)

interp.set_tensor(inp["index"], data)

t0 = time.perf_counter()
interp.invoke()
t_first = (time.perf_counter() - t0) * 1e3

times = []
for _ in range(5):
    t = time.perf_counter()
    interp.invoke()
    times.append((time.perf_counter() - t) * 1e3)

probs = interp.get_tensor(out["index"])[0]
top1  = int(np.argmax(probs))
conf  = float(probs[top1])

print(f"First-compile: {t_first:.1f} ms")
print(f"Steady-state:  avg={sum(times)/len(times):.1f} ms  min={min(times):.1f} ms")
print(f"Top-1 index:   {top1}  conf={conf:.3f}")
print("INFERENCE OK")
