#!/bin/sh
# Tomeu #55 faithful replay. Capture FIRST (fresh /rknpu_replay incl. submit.bin +
# full submit fields in meta.txt), then replay that exact capture through the rknn
# UABI -- submit copied verbatim from submit.bin, only task_obj_addr re-pointed.
# If this still stalls at task 0->1, the difference is below the UABI entirely.
CAPDIR=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 4 2>/dev/null

echo "----- capture (runner, fresh /rknpu_replay + submit.bin) -----"
rm -rf /rknpu_replay
LD_PRELOAD="$CAPDIR/capture.so" "$CAPDIR/runner" "$CAPDIR/conv2d_rk3576.rknn" ramp 2>&1 | grep -aE "CAPTURE|rknn_|DONE"
echo "submit fields:"; grep -aE "priority|subcore0|task_number=" /rknpu_replay/meta.txt

dmesg -C 2>/dev/null
echo ""
echo "----- FAITHFUL REPLAY (verbatim submit from submit.bin) -----"
"$CAPDIR/replay" /rknpu_replay 2>&1
echo "----- kernel -----"
dmesg | grep -aE "rknpu est\[|job timeout|failed to wait|task counter|OUT iova" | tail -8
sync
