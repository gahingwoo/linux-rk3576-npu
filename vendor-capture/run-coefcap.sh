#!/bin/sh
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Catch the VENDOR's coefficient buffer for conv2d-cal's geometry on its way to
# the hardware, and print it, so it can be fed back to the open driver through
# ROCKET_BIAS_FILE.
#
# WHY THE FILE IS NOT ENOUGH. abc_locate finds g_cal's A, B and C at 0x8540 in
# the .rknn, but the 256 bytes after that table are zero in the file and the
# bytes after those are weights. The runtime assembles the buffer at load time,
# so the layout on disk is not the layout the hardware reads, and there is
# nothing to dd out.
#
# WHY IT IS PRINTED RATHER THAN SAVED. The files land on the card, and the card
# is not the machine the analysis happens on. The console is, and 1280 bytes of
# hex is small enough to read back out of the log.
#
# WHAT IT IS FOR. Four rounds of sweeping the open driver's own knobs moved the
# output by a few counts and never once restored the half below the output zero
# point. The vendor's userspace on this silicon does produce that half, measured
# at conv2d-cal's exact geometry and zero point. So the next question is not
# which knob but which BYTES, and the way to ask it is to give the open driver
# the vendor's buffer and see whether the half comes back. The answer will be
# numerically wrong, because the weights belong to a different model, and that
# does not matter for this question.
CAP=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 4 2>/dev/null

echo ""
echo "===== 1) CAPTURE g_cal, conv2d-cal's geometry, out_zp 120         ====="
rm -rf /rknpu_replay
LD_PRELOAD=$CAP/capture.so $CAP/runner $CAP/g_cal_rk3576.rknn ramp 2>&1 \
	| grep -aE "CAPTURE|rknn_init|n_output|n_input"

echo ""
echo "===== 2) WHAT WAS CAUGHT. meta.txt names the buffers and their    ====="
echo "=====    addresses, and 0x5020 in the register stream says which  ====="
echo "=====    of them the coefficients are.                            ====="
cat /rknpu_replay/meta.txt 2>/dev/null
for f in /rknpu_replay/bo*.bin; do
	[ -e "$f" ] || continue
	echo "  $(basename $f) size=$(wc -c <"$f") md5=$(md5sum "$f" | cut -d' ' -f1)"
done

echo ""
echo "===== 3) FIND THE RECORDS INSIDE THE BUFFERS. Two passes dumped  ====="
echo "=====    offset zero of each and none of them opened with the    ====="
echo "=====    table: bo00 is a descriptor list, bo01 is weights, bo03  ====="
echo "=====    is the ramp input, bo02 and bo04 start zeroed. So the    ====="
echo "=====    records sit at an offset inside one of them, and this    ====="
echo "=====    searches for them by their bytes AND by their shape.     ====="
python3 $CAP/find_coef.py c9e4feff80defbfff5d60200971d0000 /rknpu_replay/bo*.bin

echo ""
echo "===== Read entry 2 first. If no bo files appeared the preload did ====="
echo "===== not catch anything and entry 3 is empty rather than wrong.  ====="
sync
