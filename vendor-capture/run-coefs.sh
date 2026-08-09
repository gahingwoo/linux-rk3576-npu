#!/bin/sh
# ---------------------------------------------------------------------------
# VENDOR coefficient buffer capture, 2026-08-09.
#
# The open driver computes a 5x5 convolution correctly and the same model with
# its kernel cropped to 3x3 or 1x1 returns nothing useful. For those every byte
# and every register the driver produces has been verified against a vendor
# .rknn compiled at the same geometry: the register stream in absolute terms,
# the weight buffer layout including the 32-channel grouping, the bias tensor,
# the requant, and the A, B and C coefficients. An input impulse lands in the
# right output pixels, so no tap is paired with the wrong input.
#
# The simplest failing case is a constant input at the input zero point, where
# every MAC product is zero by construction and the answer has to be
# requant(bias). The 5x5 returns exactly that; the 3x3 returns the zero point
# everywhere and the 1x1 returns values below it. Same bias, same requant, same
# A, B and C. So something k-dependent is reaching the block that the driver
# does not write.
#
# The one buffer that could still carry it is the coefficient buffer, and its
# contents CANNOT be read offline: a .rknn holds the weights but not the A/B/C
# table or the float surface, which librknnrt builds at load time. Hence this
# capture.
#
# Two models, same 16 in / 128 out / 80x80 / stride 2, differing only in kernel:
#   g_cal_rk3576.rknn     5x5, the geometry that computes on the open driver
#   g_cal_k3_rk3576.rknn  3x3, the one that does not
#
# WHAT IT DECIDES, stated before the run:
#   the two coefficient buffers are byte identical  -> the coefficient buffer is
#       excluded, exactly as mesa's own is, and whatever depends on the kernel
#       sits below everything either driver writes
#   they differ                                     -> the difference is the
#       answer and can be carried straight into mesa
#
# The kernel patch now allows four BO dumps per boot instead of one, so both
# models are captured in a single boot and each dump is numbered.
# ---------------------------------------------------------------------------
CAPDIR=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 7 2>/dev/null

echo "===== VENDOR coefficient buffer capture: 5x5 then 3x3 ====="
echo ""
echo "----- 1) k=5, the geometry the open driver computes correctly -----"
"$CAPDIR/runner" "$CAPDIR/g_cal_rk3576.rknn" ramp 2>&1 | grep -aE "rknn_|DONE|Top"
sleep 1
echo ""
echo "----- 2) k=3, the geometry it does not -----"
"$CAPDIR/runner" "$CAPDIR/g_cal_k3_rk3576.rknn" ramp 2>&1 | grep -aE "rknn_|DONE|Top"
sleep 1

echo ""
echo "===== PCDISP for both, to confirm two distinct submits ====="
dmesg | grep -aE "rknpu cap: PCDISP" | head -4

echo ""
echo "===== BO DUMP headers, one per model ====="
dmesg | grep -aE "rknpu cap: ==== BO DUMP" | head -4

echo ""
echo "===== the coefficient buffer, both models ====="
echo "  (A/B/C table is groups*64 = 1024 bytes for 128 output channels;"
echo "   anything past that is the float surface mesa leaves zeroed)"
dmesg | grep -aE "rknpu cap: BO bias" | head -140

echo ""
echo "===== weights and output, for orientation ====="
dmesg | grep -aE "rknpu cap: BO (weights|output) iova" | head -6

echo ""
echo "===== compare the two bias dumps. Identical means the coefficient  ====="
echo "===== buffer is excluded on the vendor side too.                   ====="
sync
echo "===== DONE ====="
