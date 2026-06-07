#!/usr/bin/env bash
# Flash dirty/sdcard.img to an SD card.
# Must run as root: sudo bash flash.sh [/dev/sdX]
#
# Build the image first:  bash make-sdimage.sh
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "ERROR: run as root: sudo bash $0"; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
IMG="${REPO}/dirty/sdcard.img"
DEV="${1:-/dev/sdb}"

# ── Safety ────────────────────────────────────────────────────────────────────
BASENAME="$(basename "$DEV")"
if [[ "$BASENAME" == "sda" || "$BASENAME" == "nvme0n1" || "$BASENAME" == "mmcblk0" ]]; then
    echo "ERROR: refusing to write to ${DEV} — looks like the primary disk"
    exit 1
fi
[[ -b "$DEV" ]]  || { echo "ERROR: ${DEV} is not a block device"; exit 1; }
[[ -f "$IMG" ]]  || { echo "ERROR: ${IMG} not found — run:  bash make-sdimage.sh"; exit 1; }

IMG_MB=$(( $(stat -c%s "$IMG") / 1024 / 1024 ))
DEV_MB=$(( $(blockdev --getsize64 "$DEV") / 1024 / 1024 ))
echo "Image:  ${IMG}  (${IMG_MB} MiB)"
echo "Target: ${DEV}   (${DEV_MB} MiB)"
echo ""

umount "${DEV}"?* 2>/dev/null || true
sleep 1

dd if="${IMG}" of="${DEV}" bs=4M status=progress
sync

partprobe "$DEV" 2>/dev/null || blockdev --rereadpt "$DEV" 2>/dev/null || true

echo ""
echo "==> Flash complete."
echo ""
echo "Boot partition contents:"
PART="${DEV}1"
if [[ -b "$PART" ]]; then
    mkdir -p /tmp/rock4d-verify
    mount "$PART" /tmp/rock4d-verify 2>/dev/null && ls -lh /tmp/rock4d-verify && umount /tmp/rock4d-verify || true
fi
