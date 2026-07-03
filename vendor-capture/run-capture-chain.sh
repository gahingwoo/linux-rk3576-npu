#!/bin/sh
# CHAIN payload capture (conv0->dw1->pw1->dw2). Runs the 4-layer chain through the
# vendor rknn stack under capture.so, which dumps the WHOLE-GRAPH payload (task
# array + all BOs incl. the conv0-output/dw1-input intermediate) to /rknpu_replay.
# Replaying this SPREAD on rocket tests whether dw1 (the layer AFTER conv0, reading
# conv0's device-written output) computes in-chain -- isolating the conv0->dw
# context wall (HW/kernel) from a mesa-specific job-build issue.
CAPDIR=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 7 2>/dev/null
dmesg -C 2>/dev/null

echo "===== VENDOR CHAIN capture: conv0->dw1->pw1->dw2 (for conv0->dw1 context replay) ====="
LD_PRELOAD="$CAPDIR/capture.so" "$CAPDIR/runner" "$CAPDIR/chain_rk3576.rknn" ramp 2>&1 \
	| grep -aE "CAPTURE|rknn_|DONE|Top|task_number"
echo ""
echo "----- payload dumped to /rknpu_replay (pull this dir) -----"
ls -la /rknpu_replay 2>/dev/null
echo "----- meta (task_number = total tiles across the 4 layers) -----"
head -20 /rknpu_replay/meta.txt 2>/dev/null
sync
echo "===== DONE ====="
