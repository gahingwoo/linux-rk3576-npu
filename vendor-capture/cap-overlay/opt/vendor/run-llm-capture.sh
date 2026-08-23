#!/bin/sh
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Capture ONE int4 op from the vendor's own LLM runtime, with the buffers.
#
# WHY. charsiu now runs the vendor's exact int4 register configuration, all 117
# of them, and it computes a bit pattern product rather than a weighted sum: the
# effective weight for nibble v is fp16bits(v), which spans only 0 and the band
# 1.00 to 1.18. Every register that differed has been tried and none of them
# changes it. So the difference is not in the stream, it is in what the stream
# points AT, and that is what this captures.
#
# capture.so is an ioctl interposer: it records every buffer the runtime creates
# and, on the first submit, writes the submit struct, the task array and every
# buffer to /rknpu_replay. It does not care which runtime is above it.
#
# What the analysis needs from the dump: the regcmd (to know the shape and which
# op it is), the WEIGHT buffer, the INPUT buffer and the OUTPUT buffer. With the
# same model on the host we know what the weights should be, so their bytes plus
# their result says what value the hardware gives each 4 bit code.
set -eu
V=/opt/vendor
M="${1:-$V/model/Llama-3.2-1B-Instruct-rk3576-w4a16.rkllm}"

[ -f "$M" ] || { echo "no model at $M"; exit 1; }
[ -c /dev/dri/card0 ] || [ -c /dev/rknpu ] || echo "warning: no npu device node seen"

rm -rf /rknpu_replay
mkdir -p /rknpu_replay
echo "=== capturing one submit from the vendor LLM runtime ==="
LD_LIBRARY_PATH=$V LD_PRELOAD=$V/capture.so \
	"$V/llm_demo" "$M" 8 128 </dev/null || true
echo "=== dump ==="
ls -l /rknpu_replay/ || true
[ -f /rknpu_replay/meta.txt ] && cat /rknpu_replay/meta.txt
