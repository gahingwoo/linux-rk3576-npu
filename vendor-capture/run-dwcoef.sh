#!/bin/sh
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Capture the vendor runtime's COEFFICIENT buffer for a DEPTHWISE layer.
#
# Why this needs the board at all, when the regular-conv version of the same
# question was answered on the host: the depthwise coefficients are not in the
# .rknn. A full-file sweep of the depthwise model, int32, int16 and float32,
# seven strides, every base offset, against the known bias, the known
# per-channel weight sum, five linear combinations of the two, and the
# per-channel-scaled forms bias/wt_sc_c and sw/wt_sc_c, found exactly one thing:
# the raw float32 bias at 0x06018, byte for byte, and only in the build with
# compress_weight off. That is the unquantised source value, which the hardware
# cannot consume. Two structural oracles separately found no A/B/C table, and
# three readings found nothing in the 576-byte weight buffer.
#
# So librknnrt builds the depthwise per-channel coefficients at load time into a
# buffer the model file never contains, and the only way to see them is to catch
# the buffer on its way to the hardware.
#
# The models are the SINGLE-VARIABLE PAIR from sv_pairs.py, ic = oc = 32 at
# 112x112, k=3, s=1, one calibration set, only `groups` differing. Their weights
# and biases are known here EXACTLY, which is what makes the captured bytes
# decodable: dwcoef_decode.py correlates every per-channel column in the capture
# against those known values, and sv_rgu is the positive control that must
# produce a hit before anything sv_dwu says is worth reading.
#
# ⚠ Needs rock4d-spi-uboot-vendor.img in SPI, and rock4d-spi-uboot.img back
# afterwards before rocket will run again.
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
	LD_PRELOAD=$CAP/capture.so $CAP/runner $CAP/$model ramp 2>&1 \
		| grep -aE "CAPTURE|rknn_init|n_output|n_input"
	if [ -f /rknpu_replay/bo01.bin ]; then
		mkdir -p $OUT/$tag
		cp /rknpu_replay/*.bin /rknpu_replay/meta.txt $OUT/$tag/ 2>/dev/null
		for f in $OUT/$tag/*.bin; do
			echo "  $tag $(basename $f) size=$(wc -c <"$f") md5=$(md5sum "$f" | cut -d' ' -f1)"
		done
	else
		echo "$tag CAPTURE FAILED (no bo01)"
	fi
}

# The control goes FIRST. If the regular model's capture does not decode, the
# depthwise one cannot be read either and the round is void.
cap_one sv_rgu sv_rgu_rk3576.rknn
cap_one sv_dwu sv_dwu_rk3576.rknn

echo "===== DONE. Pull /opt/npu-cap/out/ from SD partition 2, then:  ====="
echo "=====   vendor-capture/dwcoef_decode.py out/sv_rgu out/sv_dwu  ====="
sync
