#!/bin/sh
# Build rocket.ko against the tree's own vmlinux, stamped with the release
# string the BOARD is running, so modprobe's vermagic check passes.
#
#   sh build-rocket-ko.sh [RELEASE]     default: the tree's last-built release
#
# ⚠ NEEDS Module.symvers, i.e. a full `make Image modules` first. Without it
# modpost cannot resolve the kernel's exports and refuses to link the module.
# ⚠ CONFIG_MODVERSIONS is off in this .config, so no symbol CRCs are checked;
# the vermagic string is the only thing that has to match `uname -r`.
# ⚠ vermagic COMES FROM include/generated/utsrelease.h, NOT from KERNELRELEASE
# on the command line -- the first version of this script passed KERNELRELEASE
# and got the tree's own string back. An external-module build (M=) does not
# regenerate that header, so it is written with the board's string for the
# build and put back after.
set -eu
LNEXT=/home/parallels/Desktop/rock4d_package/kernel-build/linux-next
OUT=$(cd "$(dirname "$0")" && pwd)
REL=${1:-$(cat "$LNEXT/include/config/kernel.release")}
UTS="$LNEXT/include/generated/utsrelease.h"
[ -f "$LNEXT/Module.symvers" ] || { echo "no Module.symvers: run the full build first"; exit 1; }
cp -p "$UTS" "$UTS.orig"
trap 'mv -f "$UTS.orig" "$UTS"' EXIT
printf '#define UTS_RELEASE "%s"\n' "$REL" >"$UTS"
make -C "$LNEXT" -s M=drivers/accel/rocket clean
make -C "$LNEXT" -s -j"$(nproc)" M=drivers/accel/rocket modules
cp "$LNEXT/drivers/accel/rocket/rocket.ko" "$OUT/rocket.ko"
GOT=$(modinfo "$OUT/rocket.ko" | sed -n 's/^vermagic: *\([^ ]*\).*/\1/p')
[ "$GOT" = "$REL" ] || { echo "vermagic came out $GOT, wanted $REL"; exit 1; }
modinfo "$OUT/rocket.ko" | grep -E "^vermagic|^srcversion"
sha256sum "$OUT/rocket.ko"
