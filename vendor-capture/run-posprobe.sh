#!/bin/sh
# Decisive placement probe: two MATCHED-shape (per-tensor 16->128 5x5) convs.
#  posprobe_a = OIHW position RAMP weights, posprobe_b = different random weights.
# Compare their coef float-surface nonzero masks off-board: Jaccard->1 (same slots,
# different values) = placement is POSITION-FIXED = derivable; <1 = value-dependent.
# If position-fixed, posprobe_a's *37 mod 251 ramp decodes each window's OIHW start.
CAP=/opt/npu-cap; OUT=$CAP/out
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
rm -rf $OUT; mkdir -p $OUT
i=0; while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i+1)); done
sleep 2; dmesg -n 4 2>/dev/null
cap_one() {
	tag=$1; model=$2
	echo "===== CAPTURE $tag ($model) ====="
	rm -rf /rknpu_replay
	LD_PRELOAD=$CAP/capture.so $CAP/runner $CAP/$model ramp 2>&1 | grep -aE "CAPTURE|rknn_init"
	if [ -f /rknpu_replay/bo01.bin ]; then
		mkdir -p $OUT/$tag; cp /rknpu_replay/*.bin /rknpu_replay/meta.txt $OUT/$tag/ 2>/dev/null
		echo "  $tag bo01 size=$(wc -c <$OUT/$tag/bo01.bin) md5=$(md5sum $OUT/$tag/bo01.bin|cut -d' ' -f1)"
	else echo "$tag FAILED"; fi
}
cap_one posprobe_a posprobe_a.rknn
cap_one posprobe_b posprobe_b.rknn
cap_one posprobe_c posprobe_c.rknn
cap_one posprobe_d posprobe_d.rknn
echo "===== DONE: pull /opt/npu-cap/out/ from SD part 2 ====="
sync
