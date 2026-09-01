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
set -eu
LNEXT=/home/parallels/Desktop/rock4d_package/kernel-build/linux-next
OUT=$(cd "$(dirname "$0")" && pwd)
REL=${1:-$(cat "$LNEXT/include/config/kernel.release")}
[ -f "$LNEXT/Module.symvers" ] || { echo "no Module.symvers: run the full build first"; exit 1; }
make -C "$LNEXT" -s KERNELRELEASE="$REL" M=drivers/accel/rocket clean
make -C "$LNEXT" -s -j"$(nproc)" KERNELRELEASE="$REL" M=drivers/accel/rocket modules
cp "$LNEXT/drivers/accel/rocket/rocket.ko" "$OUT/rocket.ko"
modinfo "$OUT/rocket.ko" | grep -E "^vermagic|^srcversion"
sha256sum "$OUT/rocket.ko"
