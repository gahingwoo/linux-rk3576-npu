#!/bin/sh
# Per-axis layout capture (accuracy-first): clean position-encoded pointwise/depthwise
# convs (no pad/extra ops), full BO dump so the coef offset is read from the regcmd,
# not guessed. pw_ic weight=ic+1, pw_oc weight=oc+1, dw_k weight=ky*3+kx+1; conv2d = per-tensor contrast.
CAP=/opt/npu-cap
OUT=$CAP/out
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
rm -rf $OUT; mkdir -p $OUT
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 4 2>/dev/null

cap_one() {
	tag=$1; model=$2
	echo "===== CAPTURE $tag ($model) ====="
	rm -rf /rknpu_replay
	LD_PRELOAD=$CAP/capture.so $CAP/runner $CAP/$model ramp 2>&1 | grep -aE "CAPTURE|rknn_init|n_output|n_input"
	if [ -f /rknpu_replay/bo01.bin ]; then
		mkdir -p $OUT/$tag
		cp /rknpu_replay/*.bin /rknpu_replay/meta.txt $OUT/$tag/ 2>/dev/null
		for f in $OUT/$tag/*.bin; do echo "  $tag $(basename $f) size=$(wc -c <"$f") md5=$(md5sum "$f" | cut -d' ' -f1)"; done
		sz=$(wc -c < $OUT/$tag/bo01.bin)
		if [ "$sz" -lt 12000 ]; then
			echo "-----BEGIN $tag BO01 B64-----"; base64 $OUT/$tag/bo01.bin; echo "-----END $tag BO01 B64-----"
		else
			echo "  ($tag bo01 $sz B too big for console; pull from SD)"
		fi
	else
		echo "$tag CAPTURE FAILED (no bo01)"
	fi
}

cap_one pw_ic     pw_ic.rknn
cap_one pw_oc     pw_oc.rknn
cap_one dw_k      dw_k.rknn
cap_one pertensor conv2d_rk3576.rknn
echo "===== CAPTURE DONE: pull everything in /opt/npu-cap/out/ from SD partition 2 (ext4) ====="
sync
