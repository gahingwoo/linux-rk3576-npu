#!/bin/sh
# Package a full in-tree build into the layout charsiu-install.sh's
# install_kernel() takes from a GitHub release: Image, the ROCK 4D dtb,
# modules-<release>.tar.gz holding lib/modules/<release>, and SHA256SUMS.
# Run after `make Image modules dtbs` in LNEXT.
#
#   sh package-kernel.sh [OUTDIR]
#
# ⚠ THIS IS THE HEAVY DELIVERY. For the attach-once experiment alone the board
# needs only rocket.ko with the running kernel's vermagic; see
# build-rocket-ko.sh. Publish a whole kernel only once the board has said the
# patch is good.
set -eu
LNEXT=/home/parallels/Desktop/rock4d_package/kernel-build/linux-next
OUT=${1:-$HOME/Desktop/linux-rk3576-npu/rfc-send-v12/attach-once/out}
REL=$(cat "$LNEXT/include/config/kernel.release")
DTB=arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dtb

[ -f "$LNEXT/arch/arm64/boot/Image" ] || { echo "no Image yet"; exit 1; }
[ -f "$LNEXT/$DTB" ] || { echo "no $DTB"; exit 1; }
rm -rf "$OUT"; mkdir -p "$OUT/stage"
make -C "$LNEXT" -s modules_install INSTALL_MOD_PATH="$OUT/stage" INSTALL_MOD_STRIP=1
cp "$LNEXT/arch/arm64/boot/Image" "$OUT/Image"
cp "$LNEXT/$DTB" "$OUT/"
# ⚠⚠ NAME THE RELEASE DIRECTORY, NOT lib/. `tar ... lib` records lib/ and
# lib/modules/ as DIRECTORY MEMBERS, and GNU tar extracting a directory
# member over Armbian's /lib -> usr/lib symlink replaces the symlink with a
# real directory: the loader path is gone, nothing dynamic can exec, and the
# board panics in run-init. That is what the first tarball from this script
# did on 2026-09-02. Naming lib/modules/$REL stores that directory and its
# contents only, which is the layout the August release has and what
# `tar -C /` in the old installer survived by luck.
tar -C "$OUT/stage" -czf "$OUT/modules-$REL.tar.gz" "lib/modules/$REL"
rm -rf "$OUT/stage"
(cd "$OUT" && sha256sum Image "$(basename "$DTB")" "modules-$REL.tar.gz" >SHA256SUMS)
ls -la "$OUT"
echo "release $REL"
