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
# ⚠ THE FIRST RUN OF THIS MEASURED NOTHING, and the control is what said so.
#
# The output tensor is INT8, rknn_tensor_type 2, and its zero point is in the
# same domain: these models report -128, 17 and -14, not 0, 145 and 114. The
# runner read the buffer as unsigned bytes and compared them against a signed
# zero point, so a_relu could not report anything below -128 and passed
# vacuously, while the two linear models disagreed with each other, 19.75
# percent against 0, when both have about 58 percent of their float output
# negative. Two models that must agree did not, so the instrument was wrong
# rather than the hardware, and no verdict from that run counts.
#
# a_relu was never a control either. Its zero point IS the bottom of the int8
# range, so nothing can sit below it whatever the hardware does. It cannot
# fail. The real control is a_lin2 agreeing with a_lin.
#
# THE DECISION RULE, WRITTEN BEFORE THE RUN.
#
#   an interrupt count does not move across an inference
#             that inference did not reach the NPU and its numbers are
#             librknnrt's, not the hardware's. This is the control the first
#             two runs of this script did not have, and it is the one Igor used
#             on the other SoC to rule the same thing out.
#   a_lin and a_lin2 DISAGREE with each other
#             the instrument is wrong again and nothing else here counts. They
#             are both linear with 58.6 and 58.0 percent of their float output
#             negative, and float < 0 is exactly q < zp, so they have to land
#             within a point or two of each other.
#   a_lin reports about 58 percent below out_zp
#             ⚠ RUN 2 ALREADY SAID THIS, 60.50 percent with a_lin2 at 59.08,
#             both within two points of the host prediction. What that run
#             lacked was the interrupt control above, so this one is the same
#             measurement with the last hole closed rather than a new question.
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

# ⚠ THE CONTROL THIS ROUND WAS MISSING. Nothing showed the inference reached the
# NPU rather than falling back inside librknnrt, which is the same worry Igor
# raised about a result that looks like the CPU's. He answered it with per core
# interrupt counters, so answer it the same way: read the NPU interrupt line
# before and after, and print the debugfs load beside it. A count that does not
# move means the number above it came from software.
npu_irq() {
	awk '/npu|rknpu|NPU/ {s=0; for (i=2;i<=NF;i++) if ($i ~ /^[0-9]+$/) s+=$i;
	     printf "%s%s", (n++?" ":""), s} END {if (!n) printf "none"}' /proc/interrupts
}
npu_load() {
	cat /sys/kernel/debug/rknpu/load 2>/dev/null | tr -d '\n' || printf "no debugfs load"
}
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 4 2>/dev/null

echo ""
echo "===== 0) DID IT REACH THE NPU. The interrupt count has to move    ====="
echo "=====    across each inference, or the numbers below came from     ====="
echo "=====    software rather than from the hardware.                   ====="
echo "  npu irq before everything: $(npu_irq)    load: $(npu_load)"

echo ""
echo "===== 1) a_relu. Its zero point IS the bottom of the int8 range,   ====="
echo "=====    so nothing can sit below it whatever the hardware does.   ====="
echo "=====    This one cannot fail and is not a control.                ====="
B=$(npu_irq); $CAP/runner_out $CAP/a_relu_rk3576.rknn 2>&1
echo "  npu irq $B -> $(npu_irq)"

echo ""
echo "===== 2) THE MEASUREMENT. a_lin is 58.6 percent negative in float. ====="
B=$(npu_irq); $CAP/runner_out $CAP/a_lin_rk3576.rknn 2>&1
echo "  npu irq $B -> $(npu_irq)"

echo ""
echo "===== 3) THE REPRODUCIBILITY CONTROL. a_lin2, linear again with    ====="
echo "=====    different weights, 58.0 percent negative in float. It has ====="
echo "=====    to land within a point or two of a_lin.                   ====="
B=$(npu_irq); $CAP/runner_out $CAP/a_lin2_rk3576.rknn 2>&1
echo "  npu irq $B -> $(npu_irq)"

echo ""
echo "===== Entry 1 first. Then read the BELOW out_zp line of entry 2.   ====="
echo "===== About 58 percent means the hardware can and the open driver  ====="
echo "===== is missing something. Zero means the clamp is the hardware.  ====="
sync
