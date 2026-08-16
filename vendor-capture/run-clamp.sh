#!/bin/sh
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# CAN THIS HARDWARE PUT A VALUE BELOW ITS OUTPUT ZERO POINT AT ALL.
#
# On the open driver every convolution whose output range is symmetric loses its
# entire negative half. conv2d-cal, out_zp 128 and no fused activation, comes
# back equal to max(cpu, 128) to within one EVERYWHERE, the raw rows included,
# so the arithmetic above the zero point is exact and 100820 of 204800 pixels
# land on exactly 128. Scored against the unclamped output that model is 0 of
# 128 channels, not 128 of 128.
#
# Everything reachable from the open side has been excluded.
#   the output offset      moving it moves those pixels with it, so the clamp is
#                          upstream of the offset and the store is not it
#   the BS block           all four values including an explicit zero are byte
#                          identical
#   the register stream    the same register set as the vendor in all four
#                          units, and for the same model the same values apart
#                          from addresses, the model's own requant, its pad
#                          value and its padding
#   the coefficient records a_relu and a_lin share a seed and their A, B and C
#                          are identical on all 64 channels, while the linear
#                          control moves all three
#
# So the question is the hardware's, and the vendor's own compiler answers it.
# geom/a_lin is a linear convolution the vendor quantised to out_zp 145, a zero
# point its own calibration chose and would not have chosen for a non negative
# range.
#
# THE NUMBER TO COMPARE AGAINST, computed on the host from the same weights and
# the same ramp this script feeds, in float, before any of this ran.
#
#   a_lin    4096 outputs, float range -237.72 to 181.45, 2400 negative = 58.6%
#   a_lin2   4096 outputs, float range -211.75 to 260.84, 2375 negative = 58.0%
#   a_relu   4096 outputs, float range 0 to 181.45, 0 negative = 0%
#
# THE DECISION RULE, WRITTEN BEFORE THE RUN.
#
#   a_lin reports about 58 percent below out_zp
#             the hardware CAN produce a value below its output zero point, the
#             vendor gets it and the open driver does not, and the difference is
#             something neither the register stream nor the coefficient records
#             carry. Every green number on a middle zero point model is then a
#             driver bug and not a hardware limit.
#   a_lin reports nothing below out_zp and a minimum of exactly 145
#             the clamp is the hardware. The open driver is not at fault, the
#             vendor's own compiler is choosing zero points its parts cannot
#             reach, and the useful output of the round is that this is a
#             property of RK3576 worth telling the list.
#   a_relu reports anything other than zero below its zero point
#             the counter is wrong and neither of the above can be read.
#
# a_relu is the null control and a_lin2 the reproducibility one, a second
# linear model with different weights that must land near the same percentage.
#
# ⚠ This is the VENDOR image. It needs rock4d-spi-uboot-vendor.img in SPI, and
# rock4d-spi-uboot.img back afterwards before rocket will run again.
CAP=/opt/npu-cap
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 4 2>/dev/null

echo ""
echo "===== 1) THE NULL CONTROL. a_relu is 0 percent negative in float, ====="
echo "=====    so it must report 0 below its zero point. If it does not, ====="
echo "=====    the counter is wrong and nothing else here counts.        ====="
$CAP/runner_out $CAP/a_relu_rk3576.rknn 2>&1

echo ""
echo "===== 2) THE MEASUREMENT. a_lin is 58.6 percent negative in float  ====="
echo "=====    and the vendor quantised it to out_zp 145.                ====="
$CAP/runner_out $CAP/a_lin_rk3576.rknn 2>&1

echo ""
echo "===== 3) THE REPRODUCIBILITY CONTROL. a_lin2, linear again with    ====="
echo "=====    different weights, 58.0 percent negative in float.        ====="
$CAP/runner_out $CAP/a_lin2_rk3576.rknn 2>&1

echo ""
echo "===== Entry 1 first. Then read the BELOW out_zp line of entry 2.   ====="
echo "===== About 58 percent means the hardware can and the open driver  ====="
echo "===== is missing something. Zero means the clamp is the hardware.  ====="
sync
