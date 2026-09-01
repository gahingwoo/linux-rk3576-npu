#!/bin/sh
# Swap the running rocket module for the one built with "keep the IOMMU
# domain attached across jobs", keeping the old one to swap back.
#
#   sh board-swap-rocket-ko.sh rocket.ko        install and reload
#   sh board-swap-rocket-ko.sh --revert         put the original back
#
# ⚠ THE MODULE HAS TO MATCH THE RUNNING KERNEL. It is built from the same
# tree and the same .config as the Image the board boots, and modinfo's
# vermagic is checked against uname -r below before anything is touched.
# ⚠ NOTHING MAY HOLD THE NPU OPEN: stop charsiu_serve and any run first.
set -eu
REL=$(uname -r)
DST=/lib/modules/$REL/kernel/drivers/accel/rocket/rocket.ko
BAK=$DST.orig

if [ "${1:-}" = "--revert" ]; then
	[ -f "$BAK" ] || { echo "no $BAK to revert to"; exit 1; }
	cp -f "$BAK" "$DST"; depmod -a
	rmmod rocket 2>/dev/null || true
	modprobe rocket
	echo "reverted; $(dmesg | grep -c 'Rockchip NPU core') core lines in dmesg"
	exit 0
fi

KO=${1:?usage: board-swap-rocket-ko.sh rocket.ko | --revert}
VM=$(modinfo "$KO" | sed -n 's/^vermagic: *\([^ ]*\).*/\1/p')
[ "$VM" = "$REL" ] || { echo "vermagic $VM does not match running $REL"; exit 1; }
[ -f "$DST" ] || { echo "no $DST -- is rocket built in on this kernel?"; exit 1; }
[ -f "$BAK" ] || cp -p "$DST" "$BAK"
cp -f "$KO" "$DST"; depmod -a
if rmmod rocket 2>/dev/null; then
	modprobe rocket
	sleep 1
	dmesg | tail -4 | grep -i "rocket\|npu" || true
	echo "reloaded. now: sh /opt/charsiu/board_verify.sh 21"
else
	echo "rocket is busy or built in; the new module loads on the next boot"
fi
