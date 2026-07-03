#!/bin/sh
# DECISIVE TEST (rocket side). Replay the vendor's captured tiled-conv payload.
# MODE=spread|onejob|both (default spread).
#   SPREAD  = N single-task jobs (Path B, one tile per job)
#   ONEJOB  = 1 job x N tasks    (the multi-task PC path, task_number>=2)
#
# IMPORTANT ordering lesson (2026-07-03): a multi-task ONEJOB job hits the engage
# wall, never completes, and leaves the DRM scheduler/fence WEDGED -- so a SPREAD
# run AFTER it fails too (PREP_BO busy, CNA reads nothing). Each mode must run on a
# CLEAN board. So MODE=spread runs ONLY spread (the load-bearing "does Path B
# actually compute the vendor's exact tiled conv" baseline). Run onejob in its own
# boot. Never run onejob before spread in the same boot.
DIR="${DIR:-/opt/npu-test/rknpu_replay}"
REF="${REPLAY_REF:-/opt/npu-test/rknn_out.bin}"
BIN="${BIN:-/opt/npu-test/replay_rocket}"
MODE="${MODE:-spread}"
[ -e /dev/accel/accel0 ] || { echo "no /dev/accel/accel0 -- boot the ROCKET image"; exit 1; }
[ -e "$REF" ] || { echo "NOTE: no ground truth at $REF -> non-degenerate only, no byte verdict"; REF=""; }

if [ "$MODE" = spread ] || [ "$MODE" = both ]; then
	echo "===== SPREAD (N jobs x 1 task = Path B) ====="
	REPLAY_REF="$REF" "$BIN" "$DIR"
	cp -f /tmp/rocket_out.bin /tmp/rocket_spread.bin 2>/dev/null
fi
if [ "$MODE" = onejob ] || [ "$MODE" = both ]; then
	echo "===== ONEJOB (1 job x N tasks = multi-task PC) ====="
	REPLAY_REF="$REF" ROCKET_REPLAY_ONEJOB=1 "$BIN" "$DIR"
	cp -f /tmp/rocket_out.bin /tmp/rocket_onejob.bin 2>/dev/null
fi
echo "==> MODE=$MODE done; pull /tmp/rocket_${MODE}.bin"
