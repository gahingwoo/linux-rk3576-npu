#!/usr/bin/env sh
# Verify the NPU test stack is ready.  tflite-runtime and numpy are
# baked into the image; this script just confirms they import correctly.
set -e

ok()   { echo "  OK: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

echo "==> Checking NPU test stack..."

python3 -c "import tflite_runtime.interpreter; print('tflite_runtime:', tflite_runtime.__version__)" \
    && ok "tflite_runtime" \
    || fail "tflite_runtime import failed — rebuild image with build.sh"

python3 -c "import numpy; print('numpy:', numpy.__version__)" \
    && ok "numpy" \
    || fail "numpy import failed — check BR2_PACKAGE_PYTHON_NUMPY=y in defconfig"

[ -f /usr/lib/libteflon.so ] && ok "libteflon.so" \
    || fail "libteflon.so not found"

[ -f /opt/npu-test/mobilenet_v1_1.0_224_quant.tflite ] && ok "model" \
    || fail "model not found — rebuild image"

echo "==> All checks passed.  Run: bash /opt/npu-test/bringup-check.sh"
