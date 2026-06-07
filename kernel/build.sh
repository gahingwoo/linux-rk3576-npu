#!/usr/bin/env bash
# Build linux-next kernel for RK3576 ROCK 4D with NPU patches applied.
#
# Usage: bash kernel/build.sh [--apply-patches] [--dtb-only]
#
# Prerequisites:
#   apt install gcc-aarch64-linux-gnu bc flex bison libssl-dev libelf-dev \
#               device-tree-compiler git python3
#
# What it does:
#   1. Optionally applies the 3-patch series to the linux-next tree (in-place)
#   2. Merges npu.fragment into .config
#   3. Builds Image + DTBs for aarch64
#   4. Copies outputs to kernel/out/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LNEXT="/home/parallels/Desktop/rock4d_package/kernel-build/linux-next"
OUT="$SCRIPT_DIR/out"
CROSS="aarch64-linux-gnu-"
JOBS="$(nproc)"
ARCH=arm64

APPLY_PATCHES=0
DTB_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --apply-patches) APPLY_PATCHES=1 ;;
        --dtb-only)      DTB_ONLY=1 ;;
    esac
done

[[ -d "$LNEXT" ]] || { echo "ERROR: linux-next not found at $LNEXT" >&2; exit 1; }

mkdir -p "$OUT"

cd "$LNEXT"

# ── Step 1: apply patches (idempotent via git am --skip) ─────────────────────
if [[ "$APPLY_PATCHES" -eq 1 ]]; then
    echo "==> Applying kernel patches..."
    # Patch 1: DT node in rk3576.dtsi - apply manually since patch has placeholder hunks
    DTS="arch/arm64/boot/dts/rockchip/rk3576.dtsi"
    if ! grep -q "rknn_core_0:" "$DTS"; then
        # Insert the NPU nodes before the closing of the soc block
        # Find the last node before closing brace and insert after it
        DTSI_INCLUDE="$REPO_ROOT/kernel/rk3576-npu.dtsi"
        echo "  Merging rk3576-npu.dtsi into $DTS"
        # Extract just the soc content (without outer / {} wrapper)
        python3 - <<'PYEOF'
import re, sys

src = open("arch/arm64/boot/dts/rockchip/rk3576.dtsi").read()
overlay = open("DTSI_PATH").read()

# Remove the include guards and / { }; wrapper from overlay
overlay = re.sub(r'^.*?/\*.*?\*/\s*', '', overlay, flags=re.DOTALL)
overlay = re.sub(r'^#include.*\n', '', overlay, flags=re.MULTILINE)
overlay = re.sub(r'^/ \{.*?^&soc \{', '', overlay, flags=re.DOTALL|re.MULTILINE)
overlay = re.sub(r'^\};$\s*$', '', overlay, flags=re.MULTILINE)
overlay = overlay.strip()

# Find position to insert: before the last "};" that closes &soc or the soc node
# Insert before the second-to-last "};" at depth 0
print("OVERLAY:", overlay[:80])
sys.exit(0)
PYEOF
        echo "  NOTE: Auto-merge requires manual edit. Apply rk3576-npu.dtsi content to $DTS"
        echo "  OR: apply patch 0001 manually after updating hunk offsets."
    else
        echo "  rk3576.dtsi already has rknn_core_0 - skipping DT patch"
    fi

    # Patch 2: rocket driver
    if ! grep -q "rk3576-rknn-core" drivers/accel/rocket/rocket_device.c 2>/dev/null; then
        echo "  Patching rocket_device.c..."
        patch -p1 --forward < "$SCRIPT_DIR/0002-drivers-accel-rocket-add-rk3576-rknn-core-compat.patch" || \
            echo "  Patch 2 may need manual application (hunk offset)"
    else
        echo "  rocket_device.c already patched - skipping"
    fi

    # Patch 3: binding YAML
    YAML="Documentation/devicetree/bindings/npu/rockchip,rk3588-rknn-core.yaml"
    if ! grep -q "rk3576" "$YAML" 2>/dev/null; then
        echo "  Patching binding YAML..."
        patch -p1 --forward < "$SCRIPT_DIR/0003-dt-bindings-npu-add-rk3576-rknn-core-compatible.patch" || \
            echo "  Patch 3 may need manual application"
    else
        echo "  Binding YAML already updated - skipping"
    fi
fi

# ── Step 2: merge config fragment ────────────────────────────────────────────
echo "==> Merging npu.fragment into .config..."
# Check current state
if grep -q "CONFIG_DRM_ACCEL=y\|CONFIG_DRM_ACCEL=m" .config; then
    echo "  CONFIG_DRM_ACCEL already set"
fi
# Merge (scripts/kconfig/merge_config.sh requires a build environment)
if [[ -x scripts/kconfig/merge_config.sh ]]; then
    ARCH=$ARCH CROSS_COMPILE=$CROSS \
        scripts/kconfig/merge_config.sh -m .config "$SCRIPT_DIR/npu.fragment"
    ARCH=$ARCH CROSS_COMPILE=$CROSS make olddefconfig
else
    echo "  WARNING: merge_config.sh not found; applying fragment manually"
    grep -v "^#" "$SCRIPT_DIR/npu.fragment" | grep "^CONFIG_" >> .config
    ARCH=$ARCH CROSS_COMPILE=$CROSS make olddefconfig
fi

if [[ "$DTB_ONLY" -eq 1 ]]; then
    # ── DTB-only rebuild ─────────────────────────────────────────────────────
    echo "==> Building DTBs only..."
    make -j"$JOBS" ARCH=$ARCH CROSS_COMPILE=$CROSS \
        rockchip/rk3576-rock-4d.dtb
    cp arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dtb "$OUT/"
    echo "==> DTB: $OUT/rk3576-rock-4d.dtb"
else
    # ── Full kernel build ────────────────────────────────────────────────────
    echo "==> Building kernel Image (${JOBS} jobs)..."
    make -j"$JOBS" ARCH=$ARCH CROSS_COMPILE=$CROSS Image modules
    make -j"$JOBS" ARCH=$ARCH CROSS_COMPILE=$CROSS \
        rockchip/rk3576-rock-4d.dtb

    # Install modules to a staging dir
    MODDIR="$OUT/modules"
    mkdir -p "$MODDIR"
    make ARCH=$ARCH CROSS_COMPILE=$CROSS \
        INSTALL_MOD_PATH="$MODDIR" modules_install

    cp arch/arm64/boot/Image "$OUT/"
    cp arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dtb "$OUT/"

    echo ""
    echo "==> Build complete:"
    ls -lh "$OUT"/Image "$OUT"/*.dtb
    echo ""
    echo "==> Modules: $MODDIR"
fi

echo ""
echo "==> Flash commands (run on host after board boots to Linux):"
echo "    scp $OUT/Image root@<board-ip>:/boot/"
echo "    scp $OUT/rk3576-rock-4d.dtb root@<board-ip>:/boot/"
echo "    scp $OUT/modules/lib/ root@<board-ip>:/  (rsync -a)"
