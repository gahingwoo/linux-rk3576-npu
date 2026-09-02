#!/bin/sh
# Put the previous kernel back. charsiu-install's kernel step keeps the kernel
# it replaced as Image.previous (and the dtb as <dtb>.previous) the FIRST time
# it installs one, and leaves that backup alone afterwards, so this restores
# the kernel the board ran before any test kernel was installed.
#
#   sh board-kernel-revert.sh        then reboot
set -eu
for b in /boot /boot/firmware; do [ -f "$b/Image.previous" ] && BOOT=$b && break; done
[ -n "${BOOT:-}" ] || { echo "no Image.previous under /boot: nothing was ever replaced"; exit 1; }
cp -f "$BOOT/Image.previous" "$BOOT/Image"
for d in "$BOOT"/dtb/*/*.dtb.previous "$BOOT"/dtb/*.dtb.previous "$BOOT"/*.dtb.previous; do
	[ -f "$d" ] && cp -f "$d" "${d%.previous}" && echo "restored ${d%.previous}"
done
sync
echo "restored $BOOT/Image from Image.previous; reboot now"
