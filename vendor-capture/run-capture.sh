#!/bin/sh
# VENDOR per-task engage capture (2026-07-02). Run a MULTI-TASK model (dw112 =
# 112-wide depthwise, tiles into ~6 tasks) on the WORKING vendor stack so the
# in-kernel est[] per-task snapshot fires: at each PC_TASK_STATUS boundary it
# dumps every unit's S_POINTER (0x_004, bit16=engage, low nibble=group) and
# S_STATUS (0x_000). This shows how the vendor re-engages/re-aligns the units
# per iterated task -- the one thing the open (rocket) driver can't do.
CAPDIR=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 7 2>/dev/null
dmesg -C 2>/dev/null

echo "===== VENDOR per-task ENGAGE capture: dw112 (multi-task depthwise) ====="
LD_PRELOAD="$CAPDIR/capture.so" "$CAPDIR/runner" "$CAPDIR/dw112_rk3576.rknn" ramp 2>&1 \
	| grep -aE "CAPTURE|rknn_|DONE|Top|task_number"

echo ""
echo "----- PCDISP (confirm multi-task: task_con/task_number) -----"
dmesg | grep -aE "rknpu cap: PCDISP" | head -2
echo "----- PER-TASK engage snapshot (est TASK ts=N: each unit sp/st) -----"
dmesg | grep -aE "rknpu est\[[0-9]\] TASK ts=" | head -24
echo "----- est settled + perf -----"
dmesg | grep -aE "rknpu est\[[0-9]\]: ever_bit16|rknpu est\[[0-9]\] perf" | head -6
sync
echo "===== DONE ====="
