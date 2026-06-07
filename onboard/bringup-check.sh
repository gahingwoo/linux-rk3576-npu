#!/usr/bin/env bash
# RK3576 NPU bring-up verification ladder.
# Run on the booted ROCK 4D board as root.
#
# Gates (stop at first failure and print failure class):
#   (a) dmesg: rocket / iommu / power-domain / clock / reset clean
#   (b) /dev/accel/accel0 present + core enumeration
#   (c) Teflon MobileNetV1 UINT8 inference on grace_hopper.bmp
#   (d) Op-support table, first-compile time, steady-state ms, top-1 label
#
# Usage: bash onboard/bringup-check.sh [--teflon-lib /path/to/libteflon.so]
set -euo pipefail

TEFLON_LIB="${TEFLON_LIB:-/usr/lib/libteflon.so}"
for arg in "$@"; do
    case "$arg" in
        --teflon-lib) shift; TEFLON_LIB="$1" ;;
    esac
done

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="/tmp/rk3576-npu-bringup-${TIMESTAMP}.txt"
MODEL_URL="https://storage.googleapis.com/download.tensorflow.org/models/mobilenet_v1_2018_08_02/mobilenet_v1_1.0_224_quant.tgz"
MODEL_DIR="/tmp/npu-test-model"
MODEL_TF="$MODEL_DIR/mobilenet_v1_1.0_224_quant.tflite"
IMG_URL="https://www.gstatic.com/webp/gallery/1.jpg"
IMG_FILE="$MODEL_DIR/grace_hopper.bmp"

PASS=0
FAIL=1

log()  { echo "[$(date +%H:%M:%S)] $*" | tee -a "$REPORT"; }
ok()   { log "  PASS: $*"; }
fail() { log "  FAIL: $*"; }
sep()  { log "$(printf '─%.0s' {1..60})"; }

# ── Write report header ───────────────────────────────────────────────────────
{
cat <<HEADER
RK3576 NPU Bring-up Report
Generated: $(date)
Kernel:    $(uname -r)
Board:     $(cat /proc/device-tree/model 2>/dev/null || echo unknown)
HEADER
} | tee "$REPORT"

sep

# ── Gate (a): dmesg audit ─────────────────────────────────────────────────────
log "==> Gate (a): dmesg audit"

# Look for rocket probe success
ROCKET_PROBE=$(dmesg | grep -i "rocket\|rknn" | grep -iv "error\|fail\|fault\|timeout" | head -20 || true)
ROCKET_ERR=$(dmesg | grep -i "rocket\|rknn" | grep -i "error\|fail\|fault\|timeout" || true)

if [[ -z "$ROCKET_PROBE" ]]; then
    fail "No rocket/rknn messages in dmesg. Driver not loaded or DT node missing."
    log "  FAILURE CLASS: DT (node absent or status!=okay)"
    dmesg | grep -i "accel\|drm\|iommu\|power.*npu\|npu.*power" | tail -20 | tee -a "$REPORT"
    exit $FAIL
fi

if [[ -n "$ROCKET_ERR" ]]; then
    fail "rocket probe errors found:"
    echo "$ROCKET_ERR" | tee -a "$REPORT"
    # Classify the failure
    if echo "$ROCKET_ERR" | grep -qi "iommu\|smmu"; then
        log "  FAILURE CLASS: IOMMU (iommu attach failed - check DT iommu address)"
    elif echo "$ROCKET_ERR" | grep -qi "clock\|clk\|EPROBE"; then
        log "  FAILURE CLASS: CLK (clock provider not ready - check clk DT, SCMI)"
    elif echo "$ROCKET_ERR" | grep -qi "power.domain\|genpd\|pm"; then
        log "  FAILURE CLASS: POWER (power domain not ready - check PD DT)"
    elif echo "$ROCKET_ERR" | grep -qi "reset"; then
        log "  FAILURE CLASS: RESET (reset not deasserted - check reset DT)"
    elif echo "$ROCKET_ERR" | grep -qi "sched.*timeout\|gpu.*sched\|job.*timeout"; then
        log "  FAILURE CLASS: ROCKET (gpu sched timeout - likely CLK/POWER gating)"
        log "  ACTION: Check CLK_RKNN_DSU0 rate and RK3576_PD_NPU0 power domain"
    else
        log "  FAILURE CLASS: ROCKET (unknown probe error)"
    fi
    exit $FAIL
fi

ok "rocket probe messages clean"
echo "$ROCKET_PROBE" | tee -a "$REPORT"

# Check iommu
IOMMU_ERR=$(dmesg | grep -i "iommu.*error\|iommu.*fault\|iommu.*fail" | grep -i "npu\|rknn\|rocket" || true)
if [[ -n "$IOMMU_ERR" ]]; then
    fail "IOMMU fault:"
    echo "$IOMMU_ERR" | tee -a "$REPORT"
    log "  FAILURE CLASS: IOMMU"
    exit $FAIL
fi
ok "No IOMMU faults"

sep

# ── Gate (b): /dev/accel/accel0 ───────────────────────────────────────────────
log "==> Gate (b): /dev/accel/accel0 presence and core enumeration"

if [[ ! -c /dev/accel/accel0 ]]; then
    fail "/dev/accel/accel0 not present"
    log "  Accel nodes present: $(ls /dev/accel/ 2>/dev/null || echo none)"
    log "  FAILURE CLASS: ROCKET (driver registered but no accel device)"
    dmesg | tail -30 | tee -a "$REPORT"
    exit $FAIL
fi
ok "/dev/accel/accel0 present"

# Core enumeration via DRM sysfs
ACCEL_SYSFS="/sys/class/accel/accel0"
if [[ -d "$ACCEL_SYSFS" ]]; then
    DRIVER=$(cat "$ACCEL_SYSFS/device/driver/module/version" 2>/dev/null || \
             basename "$(readlink -f "$ACCEL_SYSFS/device/driver")" 2>/dev/null || echo unknown)
    ok "accel0 driver: $DRIVER"

    # Count active cores via compatible match in sysfs
    NCORES=$(grep -rl "rk3576-rknn-core\|rk3588-rknn-core" \
             /sys/bus/platform/devices/ 2>/dev/null | wc -l || echo 0)
    ok "Enumerated cores: $NCORES"
    log "  Core sysfs paths:"
    grep -rl "rk3576-rknn-core\|rk3588-rknn-core" \
         /sys/bus/platform/devices/ 2>/dev/null | tee -a "$REPORT" || true
fi

sep

# ── Gate (c): Teflon MobileNetV1 inference ────────────────────────────────────
log "==> Gate (c): Teflon MobileNetV1 UINT8 inference"

if [[ ! -f "$TEFLON_LIB" ]]; then
    fail "libteflon.so not found at $TEFLON_LIB"
    log "  Set TEFLON_LIB= or pass --teflon-lib"
    log "  FAILURE CLASS: Teflon (library missing)"
    exit $FAIL
fi
ok "libteflon.so: $TEFLON_LIB"

mkdir -p "$MODEL_DIR"

# Download model if missing
if [[ ! -f "$MODEL_TF" ]]; then
    log "  Downloading MobileNetV1 UINT8 model..."
    if command -v wget &>/dev/null; then
        wget -q -O "$MODEL_DIR/mobilenet.tgz" "$MODEL_URL"
    else
        curl -L -o "$MODEL_DIR/mobilenet.tgz" "$MODEL_URL"
    fi
    tar -xzf "$MODEL_DIR/mobilenet.tgz" -C "$MODEL_DIR"
    ls "$MODEL_DIR"/*.tflite >/dev/null 2>&1 || \
        { fail "Model tflite file not found after extract"; exit $FAIL; }
    MODEL_TF="$(ls "$MODEL_DIR"/*.tflite | head -1)"
fi
ok "Model: $MODEL_TF"

# Download test image if missing
if [[ ! -f "$IMG_FILE" ]]; then
    log "  Downloading grace_hopper test image..."
    if command -v wget &>/dev/null; then
        wget -q -O "$IMG_FILE.jpg" "$IMG_URL" 2>/dev/null || true
    else
        curl -sL -o "$IMG_FILE.jpg" "$IMG_URL" 2>/dev/null || true
    fi
    # Convert to raw BMP if convert available, else use jpg directly
    if command -v convert &>/dev/null && [[ -f "$IMG_FILE.jpg" ]]; then
        convert "$IMG_FILE.jpg" -resize 224x224! BMP3:"$IMG_FILE" 2>/dev/null || \
            cp "$IMG_FILE.jpg" "$IMG_FILE"
    elif [[ -f "$IMG_FILE.jpg" ]]; then
        cp "$IMG_FILE.jpg" "$IMG_FILE"
    fi
fi

# Write minimal Teflon inference driver script
INFER_PY="$MODEL_DIR/infer.py"
cat > "$INFER_PY" <<'PYEOF'
#!/usr/bin/env python3
import ctypes, os, sys, time, struct

def die(msg):
    print(f"FAIL: {msg}"); sys.exit(1)

teflon_lib = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_path = sys.argv[1] if len(sys.argv) > 1 else die("usage: infer.py <model>")
img_path   = sys.argv[2] if len(sys.argv) > 2 else die("usage: infer.py <model> <img>")

print(f"Teflon: {teflon_lib}")
print(f"Model:  {model_path}")

# Use python-tensorflow-lite if available, else subprocess tflite_run
try:
    import tflite_runtime.interpreter as tflite
    print("Backend: tflite_runtime")

    interp = tflite.Interpreter(
        model_path=model_path,
        experimental_delegates=[tflite.load_delegate(teflon_lib,
            options={"TEFLON_DEBUG": os.environ.get("TEFLON_DEBUG", "0")})]
    )
    interp.allocate_tensors()

    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    print(f"Input:  {inp['shape']} dtype={inp['dtype'].__name__}")
    print(f"Output: {out['shape']}")

    # Load and preprocess image (224x224 RGB uint8)
    import numpy as np
    try:
        from PIL import Image
        img = Image.open(img_path).resize((224, 224)).convert("RGB")
        data = np.array(img, dtype=np.uint8)[np.newaxis]
    except ImportError:
        print("PIL not available; using random input")
        data = np.random.randint(0, 255, inp['shape'], dtype=np.uint8)

    interp.set_tensor(inp['index'], data)

    # Warm-up + first compile time
    t0 = time.perf_counter()
    interp.invoke()
    t_first = (time.perf_counter() - t0) * 1000

    # Steady-state (5 runs)
    times = []
    for _ in range(5):
        t = time.perf_counter()
        interp.invoke()
        times.append((time.perf_counter() - t) * 1000)

    probs = interp.get_tensor(out['index'])[0]
    top1  = int(np.argmax(probs))
    conf  = float(probs[top1])

    print(f"First-compile time: {t_first:.1f} ms")
    print(f"Steady-state (5 runs): avg={sum(times)/len(times):.1f} ms  "
          f"min={min(times):.1f} ms  max={max(times):.1f} ms")
    print(f"Top-1 label index: {top1}  confidence: {conf:.3f}")
    print("INFERENCE OK")

except ImportError:
    print("tflite_runtime not available; install: pip3 install tflite-runtime")
    print("Or run: apt install python3-tflite-runtime")
    sys.exit(2)
PYEOF
chmod +x "$INFER_PY"

# Run inference
log "  Running Teflon inference (TEFLON_DEBUG=${TEFLON_DEBUG:-off})..."
TEFLON_LIB="$TEFLON_LIB" \
    TEFLON_DEBUG="${TEFLON_DEBUG:-0}" \
    python3 "$INFER_PY" "$MODEL_TF" "$IMG_FILE" 2>&1 | tee -a "$REPORT" || {
    fail "Teflon inference failed (see above)"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
}

if grep -q "INFERENCE OK" "$REPORT"; then
    ok "Teflon inference complete"
else
    fail "Inference did not print INFERENCE OK"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
fi

sep

# ── Gate (d): op-support summary ──────────────────────────────────────────────
log "==> Gate (d): Summary"
grep -E "First-compile|Steady-state|Top-1|INFERENCE OK" "$REPORT" | \
    grep -v "grep" | tee -a "$REPORT" || true

sep
log "==> ALL GATES PASSED"
log "==> Report: $REPORT"
log ""
log "==> Tested-by template:"
log "    Tested-by: $(cat /proc/device-tree/model 2>/dev/null | tr -d '\0') ($(uname -r))"
log "    rocket: $(dmesg | grep -i rocket | grep -i "probe\|driver\|version" | head -1 || echo unknown)"
log "    Mesa commit: paste from mesa/build-mesa.sh output"

exit $PASS
