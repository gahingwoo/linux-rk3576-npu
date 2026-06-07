#!/usr/bin/env bash
# Build a self-contained SD card image for ROCK 4D NPU bring-up.
# No root required — uses mtools for FAT writes.
#
# Layout (MBR DOS):
#   0   – 16 MiB   : rock4d-sd-uboot.img  (idbloader @ sector 64)
#   16  – 144 MiB  : FAT32 /boot (128 MiB): boot.scr, Image, DTB, initramfs
#   Total: 144 MiB
#
# Outputs: dirty/sdcard.img
#
# Flash:
#   sudo dd if=dirty/sdcard.img of=/dev/sdb bs=4M status=progress && sync
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PKG="/home/parallels/Desktop/rock4d_package"
OUT="${REPO}/dirty/sdcard.img"

# ── Source files ──────────────────────────────────────────────────────────────
UBOOT="${PKG}/binaries/rock4d-sd-uboot.img"
KERNEL="${PKG}/kernel-build/linux-next/arch/arm64/boot/Image"
DTB="${PKG}/kernel-build/linux-next/arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dtb"
INITRAMFS="${PKG}/kernel-test/busybox-build/initramfs.cpio.gz"
BOOT_CMD="${REPO}/buildroot/board/rock4d/boot.cmd"

# ── Layout ────────────────────────────────────────────────────────────────────
UBOOT_MB=16
BOOT_MB=128
TOTAL_MB=$(( UBOOT_MB + BOOT_MB ))   # 144 MiB — no rootfs partition (initramfs)

FAT_START_SECT=32768       # sector 32768 = 16 MiB
FAT_SIZE_SECT=262144       # 128 MiB = 262144 × 512 B sectors

# ── Prereq checks ─────────────────────────────────────────────────────────────
for cmd in mkimage dd truncate sfdisk mkfs.fat mcopy mdir; do
    command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found"; \
        echo "  apt install u-boot-tools mtools"; exit 1; }
done
for f in "$UBOOT" "$KERNEL" "$DTB" "$INITRAMFS" "$BOOT_CMD"; do
    [[ -f "$f" ]] || { echo "ERROR: not found: $f"; exit 1; }
done

mkdir -p "${REPO}/dirty"

echo "Sources:"
printf "  %-20s  %s\n" "U-Boot"     "$(du -h "$UBOOT"     | cut -f1)  $UBOOT"
printf "  %-20s  %s\n" "Kernel"     "$(du -h "$KERNEL"    | cut -f1)  $KERNEL"
printf "  %-20s  %s\n" "DTB"        "$(du -h "$DTB"       | cut -f1)  $DTB"
printf "  %-20s  %s\n" "initramfs"  "$(du -h "$INITRAMFS" | cut -f1)  $INITRAMFS"
echo ""

# ── [1/5] Blank image ─────────────────────────────────────────────────────────
echo "[1/5] Creating ${TOTAL_MB} MiB image..."
truncate -s "${TOTAL_MB}M" "${OUT}"

# ── [2/5] Bootloader ──────────────────────────────────────────────────────────
echo "[2/5] Writing bootloader..."
dd if="${UBOOT}" of="${OUT}" bs=1M conv=notrunc status=none

# ── [3/5] Partition table ─────────────────────────────────────────────────────
echo "[3/5] Partition table..."
sfdisk --quiet --no-reread "${OUT}" <<SFDISK
label: dos
unit: sectors

start=${FAT_START_SECT}, size=${FAT_SIZE_SECT}, type=c
SFDISK

# ── [4/5] Build FAT32 in temp file (mtools, no mount needed) ─────────────────
echo "[4/5] Building FAT32 boot partition..."
BOOT_FAT="${REPO}/dirty/boot.fat"
truncate -s $(( BOOT_MB * 1024 * 1024 )) "${BOOT_FAT}"
mkfs.fat -F 32 -n ROCK4D "${BOOT_FAT}" >/dev/null
export MTOOLS_SKIP_CHECK=1

# Compile boot.scr
BOOT_SCR="$(mktemp /tmp/boot-XXXXXX.scr)"
trap 'rm -f "${BOOT_SCR}"' EXIT
mkimage -C none -A arm64 -T script -d "${BOOT_CMD}" "${BOOT_SCR}" >/dev/null

mcopy -i "${BOOT_FAT}" "${BOOT_SCR}"   ::boot.scr
mcopy -i "${BOOT_FAT}" "${KERNEL}"     ::Image
mcopy -i "${BOOT_FAT}" "${DTB}"        ::rk3576-rock-4d.dtb
mcopy -i "${BOOT_FAT}" "${INITRAMFS}"  ::initramfs.cpio.gz

echo ""
echo "Boot partition contents:"
mdir -i "${BOOT_FAT}" ::
echo ""

# ── [5/5] Inject FAT into image ───────────────────────────────────────────────
echo "[5/5] Assembling final image..."
dd if="${BOOT_FAT}" of="${OUT}" bs=1M seek="${UBOOT_MB}" conv=notrunc status=none
rm -f "${BOOT_FAT}"

echo ""
echo "==> ${OUT}"
ls -lh "${OUT}"
echo ""
echo "Flash:"
echo "  sudo dd if=${OUT} of=/dev/sdb bs=4M status=progress && sync"
