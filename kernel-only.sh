#!/usr/bin/env bash
# Fast kernel-only rebuild (~5 min).
# Rebuilds kernel + DTB inside the existing buildroot output tree,
# then re-runs post-image.sh to regenerate sdcard.img.
#
# Usage: ./kernel-only.sh [--dtb-only]
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LNEXT="/home/parallels/Desktop/rock4d_package/kernel-build/linux-next"
ROCKCHIP_BIN="/home/parallels/Desktop/rock4d_package/binaries"
BR_SRC="${REPO}/buildroot/br-src"
BR_OUT="${REPO}/buildroot/br-out"

DTB_ONLY=0
[[ "${1:-}" == "--dtb-only" ]] && DTB_ONLY=1

[[ -d "${BR_OUT}" ]] || { echo "ERROR: run ./build.sh first to set up buildroot output"; exit 1; }

# Refresh base.config snapshot
cp "${LNEXT}/.config" "${REPO}/kernel/base.config"

if [[ "$DTB_ONLY" -eq 1 ]]; then
    echo "==> DTB-only rebuild..."
    ROCKCHIP_BINARIES="${ROCKCHIP_BIN}" \
    make -C "${BR_SRC}" O="${BR_OUT}" linux-rebuild
else
    echo "==> Kernel rebuild ($(nproc) jobs)..."
    ROCKCHIP_BINARIES="${ROCKCHIP_BIN}" \
    make -C "${BR_SRC}" O="${BR_OUT}" linux-rebuild linux-install -j"$(nproc)"
fi

echo "==> Regenerating sdcard.img..."
ROCKCHIP_BINARIES="${ROCKCHIP_BIN}" \
BINARIES_DIR="${BR_OUT}/images" \
    bash "${REPO}/buildroot/board/rock4d/post-image.sh"

echo ""
echo "==> Done. Flash:"
echo "    dd if=${BR_OUT}/images/sdcard.img of=/dev/sdX bs=4M status=progress"
