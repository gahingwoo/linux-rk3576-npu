#!/usr/bin/env bash
# Assemble the vendor-kernel capture sdcard image:
#   our SD U-Boot + (vendor Image + vendor rk3576-rock-4d.dtb in FAT) + rootfs-cap.ext2
# Output: buildroot/br-out/images/sdcard-cap.img
set -euo pipefail

REPO=/home/parallels/Desktop/linux-rk3576-npu
IMG_DIR="$REPO/buildroot/br-out/images"
KO=/home/parallels/Desktop/rk3576-vendor-kernel/build-rk3576
ROCKCHIP_BIN=/home/parallels/Desktop/rock4d_package/binaries

UBOOT="$ROCKCHIP_BIN/rock4d-sd-uboot-vendor.img"
KERNEL="$KO/arch/arm64/boot/Image"
DTB="$KO/arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dtb"
ROOTFS="$IMG_DIR/rootfs-cap.ext2"
OUT="$IMG_DIR/sdcard-cap.img"

for f in "$UBOOT" "$KERNEL" "$DTB" "$ROOTFS"; do
  [ -f "$f" ] || { echo "MISSING: $f"; exit 1; }
done

UBOOT_MB=16; BOOT_MB=128; TOTAL_MB=$((UBOOT_MB+BOOT_MB+512))
truncate -s "${TOTAL_MB}M" "$OUT"
dd if="$UBOOT" of="$OUT" bs=1M conv=notrunc status=none

# Fixed MBR disk signature so we can boot by PARTUUID (vendor kernel enumerates
# the SD card as a non-deterministic mmcblkN — PARTUUID avoids the guess).
sfdisk --quiet "$OUT" <<SFDISK
label: dos
label-id: 0x52524b33
unit: sectors

start=32768,  size=262144, type=c
start=294912, size=1048576, type=83
SFDISK

BOOT_FAT="$(mktemp /tmp/bootcap.XXXXXX.fat)"
trap 'rm -f "$BOOT_FAT"' EXIT
truncate -s $((BOOT_MB*1024*1024)) "$BOOT_FAT"
export MTOOLS_SKIP_CHECK=1
mkfs.fat -F32 -n BOOT "$BOOT_FAT" >/dev/null
mcopy -i "$BOOT_FAT" "$KERNEL" ::Image
mcopy -i "$BOOT_FAT" "$DTB"    ::rk3576-rock-4d.dtb
EXT="$(mktemp /tmp/extlinuxcap.XXXXXX.conf)"
cat > "$EXT" <<'EOF'
default linux
prompt 0
timeout 30

label linux
    kernel /Image
    fdt /rk3576-rock-4d.dtb
    append console=ttyS0,1500000n8 earlycon=uart8250,mmio32,0x2ad40000 root=PARTUUID=52524b33-02 rootfstype=ext4 rootwait rw log_buf_len=8M
EOF
mmd  -i "$BOOT_FAT" ::extlinux
mcopy -i "$BOOT_FAT" "$EXT" ::extlinux/extlinux.conf
rm -f "$EXT"

dd if="$BOOT_FAT" of="$OUT" bs=1M seek="$UBOOT_MB" conv=notrunc status=none
dd if="$ROOTFS" of="$OUT" bs=1M seek=$((UBOOT_MB+BOOT_MB)) conv=notrunc status=progress

echo ""
echo "==> capture image: $OUT"
du -h "$OUT"
