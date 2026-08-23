#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Build rootfs-cap.ext2 for the vendor capture, unprivileged.
#
# It is buildroot's own target tree plus cap-overlay, MINUS the gguf models,
# because the vendor's .rkllm is 1.3 GB and the two together do not fit on a
# card anybody wants to write twice. mke2fs -d populates the image without a
# loop mount, so none of this needs root.
set -euo pipefail
REPO=/home/parallels/Desktop/linux-rk3576-npu
TGT="$REPO/buildroot/br-out/target"
OVL="$REPO/vendor-capture/cap-overlay"
MODEL=/home/parallels/Documents/kiln/model/Llama-3.2-1B-Instruct-rk3576-w4a16.rkllm
OUT="$REPO/buildroot/br-out/images/rootfs-cap.ext2"
MKE2FS="$REPO/buildroot/br-out/host/sbin/mke2fs"
# ⚠ NOT /tmp: it is a tmpfs and the 1.3 GB model fills it, which silently
# leaves the staged tree missing directories and builds a broken image.
STAGE=$(mktemp -d "$REPO/buildroot/br-out/caproot.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

cp -a "$TGT/." "$STAGE/"
rm -rf "$STAGE/opt/charsiu/models"                 # 2.7 GB of gguf, not needed here
cp -a "$OVL/." "$STAGE/"
mkdir -p "$STAGE/opt/vendor/model"
cp "$MODEL" "$STAGE/opt/vendor/model/"
# the capture writes here and the vendor runtime wants a writable /tmp
mkdir -p "$STAGE/rknpu_replay"

SIZE_MB=${SIZE_MB:-3072}
rm -f "$OUT"
truncate -s "${SIZE_MB}M" "$OUT"
"$MKE2FS" -q -t ext2 -d "$STAGE" -F "$OUT"
echo "==> $OUT  ($(du -h "$OUT" | cut -f1))"
