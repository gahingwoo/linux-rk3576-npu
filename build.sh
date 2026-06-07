#!/usr/bin/env bash
# Full build pipeline: extract → kernel patches → Mesa → buildroot → sdcard.img
# First run: ~30 min.  Subsequent runs (no source changes): ~2 min.
#
# Usage: ./build.sh [--skip-extract] [--skip-mesa] [--jobs N]
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LNEXT="/home/parallels/Desktop/rock4d_package/kernel-build/linux-next"
ROCKCHIP_BIN="/home/parallels/Desktop/rock4d_package/binaries"
BR_VER="2024.02.8"
BR_SRC="${REPO}/buildroot/br-src"
BR_OUT="${REPO}/buildroot/br-out"
JOBS="${JOBS:-$(nproc)}"

SKIP_EXTRACT=0
SKIP_MESA=0
for arg in "$@"; do
    case "$arg" in
        --skip-extract) SKIP_EXTRACT=1 ;;
        --skip-mesa)    SKIP_MESA=1 ;;
        --jobs)         shift; JOBS="$1" ;;
    esac
done

# ── Prerequisite check ────────────────────────────────────────────────────────
check() { command -v "$1" &>/dev/null || { echo "MISSING: $1  (install: $2)"; MISSING=1; }; }
MISSING=0
check make       "build-essential"
check gcc        "build-essential"
check python3    "python3"
check meson      "meson"
check ninja      "ninja-build"
check mformat    "mtools"
check mcopy      "mtools"
check mkimage    "u-boot-tools"
check sfdisk     "util-linux"
check wget       "wget"
[[ "$MISSING" -eq 1 ]] && { echo "Run: sudo apt install build-essential python3 meson ninja-build mtools u-boot-tools"; exit 1; }

# ── Step 1: Extract NPU values ────────────────────────────────────────────────
if [[ "$SKIP_EXTRACT" -eq 0 ]]; then
    echo "==> [1/5] Extracting NPU values..."
    bash "${REPO}/extract/values.sh"
fi

# ── Step 2: Snapshot kernel base config ───────────────────────────────────────
echo "==> [2/5] Snapshotting kernel base config..."
[[ -f "${LNEXT}/.config" ]] || { echo "ERROR: ${LNEXT}/.config not found"; exit 1; }
cp "${LNEXT}/.config" "${REPO}/kernel/base.config"

# ── Step 3: Build Mesa + libteflon.so (native, host=target=aarch64) ───────────
if [[ "$SKIP_MESA" -eq 0 ]]; then
    echo "==> [3/5] Building Mesa libteflon.so (native)..."
    bash "${REPO}/mesa/build-mesa.sh" --native
    # Stage .so files into rootfs overlay (search recursively under usr/lib/)
    STAGED=0
    while IFS= read -r -d '' so; do
        dest="${REPO}/rootfs-overlay/usr/lib/$(basename "$so")"
        mkdir -p "${REPO}/rootfs-overlay/usr/lib"
        cp "$so" "$dest"
        STAGED=$((STAGED + 1))
    done < <(find "${REPO}/mesa/out/usr/lib" -name "*.so*" -print0 2>/dev/null)
    [[ "$STAGED" -gt 0 ]] && echo "  Staged $STAGED .so files to rootfs-overlay/usr/lib/"
fi

# ── Step 3b: Stage tflite-runtime wheel (cp311 / manylinux_2_34_aarch64) ──────
TFLITE_SITE_PKG="${REPO}/rootfs-overlay/usr/lib/python3.11/site-packages"
TFLITE_SO="${TFLITE_SITE_PKG}/tflite_runtime/_pywrap_tensorflow_interpreter_wrapper.so"
TFLITE_WHL_URL="https://files.pythonhosted.org/packages/f2/e9/5fc0435129c23c17551fcfadc82bd0d5482276213dfbc641f07b4420cb6d/tflite_runtime-2.14.0-cp311-cp311-manylinux_2_34_aarch64.whl"

mkdir -p "${TFLITE_SITE_PKG}"
if [[ ! -f "${TFLITE_SO}" ]]; then
    echo "==> [3b/5] Downloading tflite-runtime 2.14.0 (cp311 aarch64)..."
    TMPWHL="$(mktemp /tmp/tflite.XXXXXX.whl)"
    wget -q --show-progress -O "${TMPWHL}" "${TFLITE_WHL_URL}"
    unzip -q "${TMPWHL}" -d "${TFLITE_SITE_PKG}"
    rm -f "${TMPWHL}"
    echo "  Staged: $(du -sh "${TFLITE_SITE_PKG}/tflite_runtime" | cut -f1)  tflite_runtime"
else
    echo "==> [3b/5] tflite-runtime already staged"
fi

# ── Step 3d: Stage NPU test model ─────────────────────────────────────────────
NPU_TEST_DIR="${REPO}/rootfs-overlay/opt/npu-test"
MODEL_NAME="mobilenet_v1_1.0_224_quant.tflite"
MODEL_TF="${NPU_TEST_DIR}/${MODEL_NAME}"
MODEL_URL="https://storage.googleapis.com/download.tensorflow.org/models/mobilenet_v1_2018_08_02/mobilenet_v1_1.0_224_quant.tgz"

mkdir -p "${NPU_TEST_DIR}"
if [[ ! -f "${MODEL_TF}" ]]; then
    echo "==> [3b/5] Downloading MobileNetV1 UINT8 model..."
    TMPTAR="$(mktemp /tmp/mobilenet.XXXXXX.tgz)"
    wget -q --show-progress -O "${TMPTAR}" "${MODEL_URL}"
    # Extract only the tflite; the tgz also contains ~40 MB of ckpt/pb files
    tar -xzf "${TMPTAR}" -C "${NPU_TEST_DIR}" --wildcards --no-anchored '*.tflite'
    rm -f "${TMPTAR}"
    FOUND="$(find "${NPU_TEST_DIR}" -name "*.tflite" -maxdepth 1 | head -1)"
    if [[ -n "$FOUND" && "$FOUND" != "$MODEL_TF" ]]; then
        mv "$FOUND" "$MODEL_TF"
    fi
    [[ -f "${MODEL_TF}" ]] || { echo "ERROR: ${MODEL_NAME} not found after extract"; exit 1; }
    echo "  Staged: $(du -sh "${MODEL_TF}" | cut -f1)  ${MODEL_NAME}"
else
    echo "==> [3b/5] NPU model already staged ($(du -sh "${MODEL_TF}" | cut -f1))"
fi

# ── Step 4: Download buildroot if needed ──────────────────────────────────────
echo "==> [4/5] Buildroot..."
if [[ ! -d "${BR_SRC}" ]]; then
    echo "  Downloading buildroot-${BR_VER}..."
    mkdir -p "${BR_SRC%/*}"
    wget -q --show-progress \
        "https://buildroot.org/downloads/buildroot-${BR_VER}.tar.gz" \
        -O /tmp/br-${BR_VER}.tar.gz
    tar -xf /tmp/br-${BR_VER}.tar.gz -C "${BR_SRC%/*}"
    mv "${BR_SRC%/*}/buildroot-${BR_VER}" "${BR_SRC}"
    rm /tmp/br-${BR_VER}.tar.gz
fi

# Configure
mkdir -p "${BR_OUT}"
make -C "${BR_SRC}" \
    O="${BR_OUT}" \
    BR2_EXTERNAL="${REPO}/buildroot" \
    rock4d_npu_defconfig

# Override kernel source with local tree (modern buildroot override mechanism)
echo "LINUX_OVERRIDE_SRCDIR = ${LNEXT}" > "${BR_OUT}/local.mk"

# ── Step 5: Full buildroot build ──────────────────────────────────────────────
ROCKCHIP_BINARIES="${ROCKCHIP_BIN}" \
make -C "${BR_SRC}" O="${BR_OUT}" -j"${JOBS}"

echo ""
echo "==> Build complete"
echo "    Image: ${BR_OUT}/images/sdcard.img"
echo ""
echo "Flash to SD card:"
echo "    dd if=${BR_OUT}/images/sdcard.img of=/dev/sdX bs=4M status=progress"
echo ""
echo "Boot and verify:"
echo "    ssh root@<board-ip> /opt/npu-test/install.sh   # first run: install tflite + model"
echo "    ssh root@<board-ip> /opt/npu-test/bringup-check.sh"
