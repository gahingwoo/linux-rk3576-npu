#!/usr/bin/env bash
set -euo pipefail

BINARIES="${1:?missing binaries dir}"
EXTERNAL_DIR="${BR2_EXTERNAL_RK3576NPU_PATH:?BR2_EXTERNAL_RK3576NPU_PATH not set}"
ROCKCHIP_BIN="${ROCKCHIP_BINARIES:-/home/parallels/Desktop/rock4d_package/binaries}"
OUT="${BINARIES}/sdcard.img"

UBOOT_IMG="${ROCKCHIP_BIN}/rock4d-sd-uboot.img"
# Partition layout (MiB):
#   0 –  16 : rock4d-sd-uboot.img  (idbloader + U-Boot)
#  16 – 144 : FAT32 /boot  (128 MiB)
# 144 – 656 : ext4 rootfs  (512 MiB, /dev/mmcblk0p2)
UBOOT_MB=16
BOOT_MB=128
TOTAL_MB=$(( UBOOT_MB + BOOT_MB + 512 ))

echo "==> post-image: building ${OUT}  (${TOTAL_MB} MiB)"

for cmd in mtools dd sfdisk mkfs.fat; do
    command -v "$cmd" &>/dev/null || { echo "ERROR: $cmd not found"; exit 1; }
done
[[ -f "${UBOOT_IMG}" ]] || { echo "ERROR: ${UBOOT_IMG} not found"; exit 1; }
[[ -f "${BINARIES}/Image" ]] || { echo "ERROR: ${BINARIES}/Image not found"; exit 1; }
[[ -f "${BINARIES}/rk3576-rock-4d.dtb" ]] || { echo "ERROR: DTB not found in ${BINARIES}"; exit 1; }
[[ -f "${BINARIES}/rootfs.ext2" ]] || { echo "ERROR: rootfs.ext2 not found"; exit 1; }

truncate -s "${TOTAL_MB}M" "${OUT}"
dd if="${UBOOT_IMG}" of="${OUT}" bs=1M conv=notrunc status=none

sfdisk --quiet "${OUT}" <<SFDISK
label: dos
unit: sectors

start=32768,  size=262144, type=c
start=294912, size=1048576, type=83
SFDISK

# Build FAT32 /boot in a temp file (mtools avoids needing root mount).
BOOT_SIZE_BYTES=$(( BOOT_MB * 1024 * 1024 ))
BOOT_FAT_IMG="$(mktemp /tmp/boot.XXXXXX.fat)"
trap 'rm -f "${BOOT_FAT_IMG}"' EXIT
truncate -s "${BOOT_SIZE_BYTES}" "${BOOT_FAT_IMG}"
export MTOOLS_SKIP_CHECK=1
mkfs.fat -F32 -n BOOT "${BOOT_FAT_IMG}" >/dev/null
mcopy -i "${BOOT_FAT_IMG}" "${BINARIES}/Image"              ::Image
mcopy -i "${BOOT_FAT_IMG}" "${BINARIES}/rk3576-rock-4d.dtb" ::rk3576-rock-4d.dtb

EXTLINUX_CONF="$(mktemp /tmp/extlinux.XXXXXX.conf)"
cat > "${EXTLINUX_CONF}" <<'EOF'
default linux
prompt 0
timeout 30

label linux
    kernel /Image
    fdt /rk3576-rock-4d.dtb
    append console=ttyS0,1500000n8 earlycon=uart8250,mmio32,0x2ad40000 root=/dev/mmcblk0p2 rootfstype=ext4 rootwait rw clk_ignore_unused
EOF
mmd  -i "${BOOT_FAT_IMG}" ::extlinux
mcopy -i "${BOOT_FAT_IMG}" "${EXTLINUX_CONF}" ::extlinux/extlinux.conf
rm -f "${EXTLINUX_CONF}"

dd if="${BOOT_FAT_IMG}" of="${OUT}" bs=1M seek="${UBOOT_MB}" conv=notrunc status=none
dd if="${BINARIES}/rootfs.ext2" of="${OUT}" bs=1M seek=$(( UBOOT_MB + BOOT_MB )) \
    conv=notrunc status=progress

echo ""
echo "==> sdcard.img ready: ${OUT}"
echo "    $(du -sh "${OUT}" | cut -f1)   Flash:"
echo "    dd if=${OUT} of=/dev/sdX bs=4M conv=fsync oflag=direct status=progress"
