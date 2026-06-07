#!/usr/bin/env bash
# One-shot: recreate the lost partition table entry on /dev/sdb.
# The FAT data starting at sector 32768 (16 MiB) is still physically intact.
# Run as root: sudo bash recover-ptable.sh [/dev/sdX]
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { echo "ERROR: sudo bash $0"; exit 1; }

DEV="${1:-/dev/sdb}"
[[ -b "$DEV" ]] || { echo "ERROR: $DEV not a block device"; exit 1; }

echo "Recreating partition table on $DEV ..."
echo "  Partition 1: FAT32, start=32768, size=1048576 (512 MiB)"
echo ""

sfdisk "$DEV" <<'SFDISK'
label: dos
unit: sectors

start=32768, size=1048576, type=c
SFDISK

partprobe "$DEV" 2>/dev/null || blockdev --rereadpt "$DEV" 2>/dev/null || true
sleep 2

PART="${DEV}1"
[[ -b "$PART" ]] || { echo "ERROR: $PART still not visible"; exit 1; }

echo ""
echo "Verifying FAT filesystem is intact..."
fsck.fat -n "$PART" 2>&1 | tail -5 || true

echo ""
echo "Mounting to check contents..."
MNT="$(mktemp -d)"
trap 'umount "$MNT" 2>/dev/null; rm -rf "$MNT"' EXIT
mount "$PART" "$MNT"
echo "Files found:"
ls -lh "$MNT"
umount "$MNT"
trap - EXIT
rm -rf "$MNT"

echo ""
echo "==> Recovery done. Now run:"
echo "    sudo bash /home/parallels/Desktop/linux-rk3576-npu/flash.sh /dev/sdb"
