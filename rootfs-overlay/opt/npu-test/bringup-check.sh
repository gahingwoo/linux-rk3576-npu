#!/usr/bin/env bash
# RK3576 NPU bring-up verification.  Run on board as root.
# Gates: (a) dmesg probe clean  (b) /dev/accel/accel0  (c) Teflon inference  (d) summary
set -euo pipefail

TEFLON_LIB="${TEFLON_LIB:-/usr/lib/libteflon.so}"
NPU_DIR="/opt/npu-test"
MODEL_TF="${NPU_DIR}/mobilenet_v1_1.0_224_quant.tflite"
INFER_PY="${NPU_DIR}/infer.py"
IMG_FILE="${NPU_DIR}/grace_hopper.jpg"
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
log "==> Gate (a): dmesg probe audit"
ROCKET_OK=$(dmesg | grep -iE "rocket|rknn" | grep -ivE "error|fail|fault|timeout" | head -20 || true)
ROCKET_ERR=$(dmesg | grep -iE "rocket|rknn" | grep -iE "error|fail|fault|timeout" || true)

if [[ -z "$ROCKET_OK" ]]; then
    fail "No rocket/rknn messages — driver not loaded or DT node missing"
    log "  FAILURE CLASS: DT"
    dmesg | grep -iE "accel|drm|iommu|power.*npu|npu.*power" | tail -20 | tee -a "$REPORT"
    exit $FAIL
fi

if [[ -n "$ROCKET_ERR" ]]; then
    fail "rocket probe errors:"
    echo "$ROCKET_ERR" | tee -a "$REPORT"
    if   echo "$ROCKET_ERR" | grep -qiE "iommu|smmu";               then log "  FAILURE CLASS: IOMMU"
    elif echo "$ROCKET_ERR" | grep -qiE "clock|clk|EPROBE";         then log "  FAILURE CLASS: CLK"
    elif echo "$ROCKET_ERR" | grep -qiE "power.domain|genpd|pm";    then log "  FAILURE CLASS: POWER"
    elif echo "$ROCKET_ERR" | grep -qiE "reset";                     then log "  FAILURE CLASS: RESET"
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
    fail "libteflon.so not found at $TEFLON_LIB"
    log "  FAILURE CLASS: Teflon (library missing)"
    exit $FAIL
}
ok "libteflon.so: $TEFLON_LIB"

[[ -f "$MODEL_TF" ]] || {
    fail "Model not found: $MODEL_TF"
    log "  Re-run build.sh on host to download model, or: bash ${NPU_DIR}/install.sh"
    log "  FAILURE CLASS: Teflon (model missing)"
    exit $FAIL
}
ok "Model: $MODEL_TF"

[[ -f "$INFER_PY" ]] || { fail "infer.py not found at $INFER_PY"; exit $FAIL; }

log "  Running inference (TEFLON_DEBUG=${TEFLON_DEBUG:-0})..."
TEFLON_LIB="$TEFLON_LIB" \
TEFLON_DEBUG="${TEFLON_DEBUG:-0}" \
    python3 "$INFER_PY" "$MODEL_TF" "$IMG_FILE" 2>&1 | tee -a "$REPORT" || {
    fail "Inference failed (see above)"
    log "  If tflite_runtime missing: pip3 install tflite-runtime==2.14.0"
    log "  FAILURE CLASS: Teflon"
    exit $FAIL
}

grep -q "INFERENCE OK" "$REPORT" || { fail "INFERENCE OK not in output"; exit $FAIL; }
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
