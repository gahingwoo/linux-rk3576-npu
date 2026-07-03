#!/bin/sh
# GROUND TRUTH (vendor/rknn side). Run the captured tiled-conv payload through the
# vendor rknn UABI -- the SAME bytes rocket will replay -- and persist the output
# as /tmp/rknn_out.bin. This is the ONE true reference: pull it and stage it on
# the rocket image as REPLAY_REF for run-verdict.sh. Boot the VENDOR image for this.
DIR="${1:-/opt/npu-test/rknpu_replay}"
BIN="${BIN:-./replay}"
[ -e /dev/rknpu ] || { echo "no /dev/rknpu -- boot the VENDOR image"; exit 1; }
"$BIN" "$DIR" || exit 1
md5sum /tmp/rknn_out.bin 2>/dev/null
echo "==> pull /tmp/rknn_out.bin and stage it as REPLAY_REF on the rocket image"
