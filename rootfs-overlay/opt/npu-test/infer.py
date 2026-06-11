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

raw = interp.get_tensor(out["index"])[0]
scale, zero_point = out["quantization"]
if scale != 0:
    probs = (raw.astype(np.float32) - zero_point) * scale
else:
    probs = raw.astype(np.float32)

top1  = int(np.argmax(probs))
conf  = float(probs[top1])

# top-5 for diagnostics
top5_idx = np.argsort(probs)[::-1][:5]

print(f"First-compile: {t_first:.1f} ms")
print(f"Steady-state:  avg={sum(times)/len(times):.1f} ms  min={min(times):.1f} ms")
print(f"Output quant:  scale={scale}  zero_point={zero_point}")
print(f"Raw non-zero:  {int(np.count_nonzero(raw))}/{len(raw)}")
print(f"Top-5: {[(int(i), round(float(probs[i]),3)) for i in top5_idx]}")
print(f"Top-1 index:   {top1}  conf={conf:.3f}")

# CPU-only reference run (no delegate)
interp_cpu = tflite.Interpreter(model_path=model_path)
interp_cpu.allocate_tensors()
inp_cpu = interp_cpu.get_input_details()[0]
out_cpu = interp_cpu.get_output_details()[0]
interp_cpu.set_tensor(inp_cpu["index"], data)
t_cpu = time.perf_counter()
interp_cpu.invoke()
t_cpu = (time.perf_counter() - t_cpu) * 1e3
raw_cpu = interp_cpu.get_tensor(out_cpu["index"])[0]
sc, zp = out_cpu["quantization"]
probs_cpu = (raw_cpu.astype(np.float32) - zp) * sc if sc != 0 else raw_cpu.astype(np.float32)
top1_cpu = int(np.argmax(probs_cpu))
top5_cpu = np.argsort(probs_cpu)[::-1][:5]
print(f"CPU ref ({t_cpu:.1f} ms): non-zero={int(np.count_nonzero(raw_cpu))}/{len(raw_cpu)}")
print(f"CPU Top-5: {[(int(i), round(float(probs_cpu[i]),3)) for i in top5_cpu]}")
print(f"CPU Top-1: {top1_cpu}  conf={float(probs_cpu[top1_cpu]):.3f}")

print("INFERENCE OK")
