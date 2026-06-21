#!/bin/sh
# Vendor-side payload capture for the conv2d BO diff (Tomeu's ask).
# Runs the SAME conv as Mesa (conv2d_rk3576.rknn, built from conv2d.tflite) with
# the SAME ramp input, so the instrumented vendor kernel dumps the payload:
#   rknpu cap: BO weights/input/bias/output  (stats + hex head)
#   rknpu cap: T0 [..] regcmd
# Copy /tmp/vendor-conv2d-cap.txt back to the host vendor-capture/ folder.
CAPDIR=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH

echo "==> npucap: waiting for /dev/rknpu ..."
i=0
while [ ! -e /dev/rknpu ] && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i+1)); done
[ -e /dev/rknpu ] || echo "npucap: WARN /dev/rknpu not present"

dmesg -n 8 2>/dev/null
dmesg -C 2>/dev/null

echo "==> npucap: running conv2d_rk3576.rknn with ramp input ..."
"$CAPDIR/runner" "$CAPDIR/conv2d_rk3576.rknn" ramp 2>&1

dmesg > /tmp/vendor-dmesg.log 2>/dev/null
grep "rknpu cap:" /tmp/vendor-dmesg.log > /tmp/vendor-conv2d-cap.txt 2>/dev/null

echo ""
echo "==> npucap: payload captured -> /tmp/vendor-conv2d-cap.txt"
echo "----- BO dump (stats) -----"
grep "rknpu cap: BO .* len=" /tmp/vendor-conv2d-cap.txt 2>/dev/null
echo "----- regcmd entry count -----"
grep -c "rknpu cap: T0 \[" /tmp/vendor-conv2d-cap.txt 2>/dev/null
echo "==> copy /tmp/vendor-conv2d-cap.txt back to host vendor-capture/"
