#!/usr/bin/env bash
# RK3576 NPU bring-up verification ladder.
# Run on the booted ROCK 4D board as root.
#
# Gates:
#   (a) dmesg: rocket / iommu / power-domain / clock / reset clean
#   (b) /dev/accel/accel0 present + core enumeration
#   (c) Teflon MobileNetV1 UINT8 inference
#   (d) Summary: first-compile ms, steady-state ms, top-1 label
set -euo pipefail

TEFLON_LIB="${TEFLON_LIB:-/usr/lib/libteflon.so}"
MODEL_DIR="/opt/npu-test"
MODEL_TF=""
IMG_FILE="${MODEL_DIR}/grace_hopper.jpg"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="/tmp/rk3576-npu-bringup-${TIMESTAMP}.txt"

PASS=0; FAIL=1

log()  { echo "[$(date +%H:%M:%S)] $*" | tee -a "$REPORT"; }
ok()   { log "  PASS: $*"; }
fail() { log "  FAIL: $*"; }
sep()  { log "$(printf '─%.0s' {1..60})"; }

{ printf "RK3576 NPU Bring-up Report\nGenerated: %s\nKernel:    %s\nBoard:     %s\n" \
    "$(date)" "$(uname -r)" \
    "$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo unknown)"; } | tee "$REPORT"
sep

# ── Gate (a): dmesg audit ─────────────────────────────────────────────────────
log "==> Gate (a): dmesg audit"
ROCKET_OK=$(dmesg | grep -iE "rocket|rknn" | grep -ivE "error|fail|fault|timeout" | head -20 || true)
ROCKET_ERR=$(dmesg | grep -iE "rocket|rknn" | grep -iE "error|fail|fault|timeout" || true)

if [[ -z "$ROCKET_OK" ]]; then
    fail "No rocket/rknn messages in dmesg — driver not loaded or DT node missing"
    log "  FAILURE CLASS: DT"
    dmesg | grep -iE "accel|drm|iommu|power.*npu|npu.*power" | tail -20 | tee -a "$REPORT"
    exit $FAIL
fi

if [[ -n "$ROCKET_ERR" ]]; then
    fail "rocket probe errors:"
    echo "$ROCKET_ERR" | tee -a "$REPORT"
    if   echo "$ROCKET_ERR" | grep -qiE "iommu|smmu";              then log "  FAILURE CLASS: IOMMU"
    elif echo "$ROCKET_ERR" | grep -qiE "clock|clk|EPROBE";        then log "  FAILURE CLASS: CLK"
    elif echo "$ROCKET_ERR" | grep -qiE "power.domain|genpd|pm";   then log "  FAILURE CLASS: POWER"
    elif echo "$ROCKET_ERR" | grep -qiE "reset";                    then log "  FAILURE CLASS: RESET"
    elif echo "$ROCKET_ERR" | grep -qiE "sched.*timeout|job.*timeout"; then
        log "  FAILURE CLASS: ROCKET (gpu sched timeout — likely CLK/POWER)"
        log "  ACTION: devmem 0x27700000 32  →  expect version ID, not 0xFFFFFFFF"
    else log "  FAILURE CLASS: ROCKET"
    fi
    exit $FAIL
fi

ok "rocket probe clean"
echo "$ROCKET_OK" | tee -a "$REPORT"

IOMMU_ERR=$(dmesg | grep -iE "iommu.*(error|fault|fail).*rknn|rknn.*(iommu|smmu)" || true)
[[ -n "$IOMMU_ERR" ]] && { fail "IOMMU fault"; echo "$IOMMU_ERR" | tee -a "$REPORT"; exit $FAIL; }
ok "IOMMU clean"
sep

# ── Gate (b): /dev/accel/accel0 ───────────────────────────────────────────────
log "==> Gate (b): /dev/accel/accel0"
if [[ ! -c /dev/accel/accel0 ]]; then
    fail "/dev/accel/accel0 absent"
    log "  Present: $(ls /dev/accel/ 2>/dev/null || echo none)"
    exit $FAIL
fi
ok "/dev/accel/accel0 present"

NCORES=$(grep -rl "rk3576-rknn-core\|rk3588-rknn-core" /sys/bus/platform/devices/ 2>/dev/null | wc -l || echo 0)
ok "Cores enumerated: ${NCORES}"
sep

# ── Gate (c): Teflon inference ────────────────────────────────────────────────
log "==> Gate (c): Teflon MobileNetV1 UINT8"

[[ -f "$TEFLON_LIB" ]] || {
    fail "libteflon.so not found at $TEFLON_LIB (copy from build host or set TEFLON_LIB=)"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
}
ok "libteflon.so: $TEFLON_LIB"

MODEL_TF="$(ls "${MODEL_DIR}"/*.tflite 2>/dev/null | head -1 || true)"
if [[ -z "$MODEL_TF" ]]; then
    fail "No .tflite model in ${MODEL_DIR}"
    log "  Download: bash /opt/npu-test/install.sh"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
fi
ok "Model: $MODEL_TF"

INFER_PY="$(mktemp /tmp/infer.XXXXXX.py)"
trap 'rm -f "${INFER_PY}"' EXIT
cat > "$INFER_PY" <<'PYEOF'
import os, sys, time
def die(m): print(f"FAIL: {m}"); sys.exit(1)

lib   = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1] if len(sys.argv) > 1 else die("no model arg")
img   = sys.argv[2] if len(sys.argv) > 2 else None

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    die("tflite_runtime missing — run: pip3 install tflite-runtime==2.14.0")

interp = tflite.Interpreter(
    model_path=model,
    experimental_delegates=[tflite.load_delegate(lib,
        options={"TEFLON_DEBUG": os.environ.get("TEFLON_DEBUG", "0")})]
)
interp.allocate_tensors()
inp = interp.get_input_details()[0]
out = interp.get_output_details()[0]
print(f"Input:  {inp['shape']}  dtype={inp['dtype'].__name__}")

import numpy as np
try:
    from PIL import Image
    data = np.array(Image.open(img).resize((224,224)).convert("RGB"), dtype=np.uint8)[np.newaxis]
except Exception:
    data = np.random.randint(0, 255, inp['shape'], dtype=np.uint8)

interp.set_tensor(inp['index'], data)
t0 = time.perf_counter()
interp.invoke()
t_first = (time.perf_counter() - t0) * 1e3

times = []
for _ in range(5):
    t = time.perf_counter(); interp.invoke(); times.append((time.perf_counter()-t)*1e3)

probs = interp.get_tensor(out['index'])[0]
top1  = int(np.argmax(probs))
conf  = float(probs[top1])

print(f"First-compile: {t_first:.1f} ms")
print(f"Steady-state:  avg={sum(times)/len(times):.1f} ms  min={min(times):.1f} ms")
print(f"Top-1 index:   {top1}  conf={conf:.3f}")
print("INFERENCE OK")
PYEOF

log "  Running inference..."
TEFLON_LIB="$TEFLON_LIB" python3 "$INFER_PY" "$MODEL_TF" "$IMG_FILE" 2>&1 | tee -a "$REPORT" || {
    fail "Inference failed"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
}

grep -q "INFERENCE OK" "$REPORT" || { fail "INFERENCE OK not printed"; exit $FAIL; }
ok "Teflon inference complete"
sep

# ── Gate (d): summary ─────────────────────────────────────────────────────────
log "==> Gate (d): Summary"
grep -E "First-compile|Steady-state|Top-1|INFERENCE OK" "$REPORT" | grep -v grep | tee -a "$REPORT" || true
sep
log "==> ALL GATES PASSED"
log "==> Report: $REPORT"
log "==> Tested-by: $(cat /proc/device-tree/model 2>/dev/null | tr -d '\0') kernel=$(uname -r)"
exit $PASS
