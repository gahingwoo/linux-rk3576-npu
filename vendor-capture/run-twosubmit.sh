#!/bin/sh
# ---------------------------------------------------------------------------
# VENDOR two-submit control. Originally 2026-07-16, CORRECTED 2026-08-06.
#
# The original staged ONE input and fired rknn_run() five times over it, then
# read "all five byte-identical" as "the vendor recomputes on every submit".
# That does not follow. A buffer nothing has written since run 0 is byte
# identical too, and on 2026-08-06 the open stack was caught doing exactly that:
# same configuration, different input, second submit left the output buffer
# untouched, and only a reset restored computation.
#
# runner_multi now stages a DIFFERENT input every run, so the test can fail:
#
#   outputs DIFFER per run  -> the vendor really does recompute warm. The
#        asymmetry with rocket is real and worth chasing.
#   outputs IDENTICAL       -> the vendor does not recompute warm either. The
#        wall is normal behaviour for this block, and the question becomes what
#        the vendor runtime does between inferences that we do not.
#
# Model: exp2_rk3576.rknn, a calibrated non-saturating single conv, so a real
# recomputation on a changed input has to move the bytes.
#
# REGIME A: one context, five back-to-back runs, gaps in ms against a 3s
#           autosuspend, so all five share one powered session.
# REGIME B: idle past the autosuspend, then one fresh submit. Positive control:
#           it must come back RICH.
# ---------------------------------------------------------------------------
CAPDIR=/opt/npu-cap
MODEL="$CAPDIR/exp2_rk3576.rknn"
BIN="$CAPDIR/runner_multi"
OUT=/tmp/twosubmit
C=/dev/console
export LD_LIBRARY_PATH=/usr/lib:$LD_LIBRARY_PATH
log() { echo "$@" > "$C"; }

mkdir -p "$OUT"
i=0
while [ ! -e /dev/dri/renderD129 ] && [ "$i" -lt 60 ]; do sleep 0.5; i=$((i + 1)); done
sleep 2
dmesg -n 7 2>/dev/null
dmesg -C 2>/dev/null

log ""
log "===== VENDOR TWO-SUBMIT CONTROL + ORDERED WRITEL TRACE (exp2 single conv, ramp) ====="
# Enable the in-kernel ordered writel trace (rknpu wt <seq> <off> <val> <caller>).
# Writing it resets the seq counter. This captures the DRIVER-level register
# ordering per submit -- the one dimension the value-only writel-audit didn't
# cover. Split submit#0 (cold, has power_on/state_init) vs submit#1.. (warm,
# just rknpu_job_subcore_commit_pc) by the caller field; diff #0 vs #1 offline.
WT=/sys/module/rknpu/parameters/wtrace
echo 1 > "$WT" 2>/dev/null && log "wtrace enabled ($(cat "$WT" 2>/dev/null))" || log "WARN: $WT not present -- kernel lacks wtrace, trace will be empty"
dmesg -C 2>/dev/null

log "----- REGIME A: one ctx, 5 back-to-back rknn_run (gap must be <3s => one power session) -----"
"$BIN" "$MODEL" 5 "$OUT" 2>&1 | tee "$OUT/A.log" > "$C"

# Persist the full ordered trace (wt + cap + armdbg) to the SD for offline diff.
dmesg 2>/dev/null | grep -aE 'rknpu (wt|cap:|armdbg)' > "$CAPDIR/vendor_wt.trace"
echo 0 > "$WT" 2>/dev/null
log "----- WRITEL TRACE: $(grep -ac 'rknpu wt' "$CAPDIR/vendor_wt.trace" 2>/dev/null) writes captured; per-caller counts: -----"
grep -a 'rknpu wt' "$CAPDIR/vendor_wt.trace" 2>/dev/null | awk '{c[$NF]++} END{for(k in c) printf "    %6d  %s\n", c[k], k}' > "$C" 2>&1
log "    (full ordered trace saved to $CAPDIR/vendor_wt.trace -- pull it for submit#0-vs-#1 diff)"

log "----- REGIME A md5 per run (different input each run, so EQUAL md5 means NOT recomputed) -----"
for f in "$OUT"/out_run0.bin "$OUT"/out_run1.bin "$OUT"/out_run2.bin "$OUT"/out_run3.bin "$OUT"/out_run4.bin; do
	[ -e "$f" ] && md5sum "$f" > "$C" 2>&1
done

log ""
log "----- REGIME B: positive control, idle 4s so the domain powers off, then one fresh submit -----"
sleep 4
"$BIN" "$MODEL" 1 "$OUT/pc" 2>&1 | tee "$OUT/B.log" > "$C"

m0=$(md5sum "$OUT/out_run0.bin" 2>/dev/null | cut -d' ' -f1)
differed=0; got=0
for i in 1 2 3 4; do
	mi=$(md5sum "$OUT/out_run$i.bin" 2>/dev/null | cut -d' ' -f1)
	[ -n "$mi" ] && got=$((got + 1))
	[ -n "$mi" ] && [ "$mi" != "$m0" ] && differed=$((differed + 1))
done
run0_rich=0; grep -q "RUN 0 .*RICH" "$OUT/A.log" && run0_rich=1
pc_rich=0;   grep -q "RUN 0 .*RICH" "$OUT/B.log" && pc_rich=1

log ""
log "=========================== VERDICT ==========================="
log " run0 RICH=$run0_rich   later runs captured=$got   differing from run0=$differed"
log " power-cycle control RICH=$pc_rich"
if [ "$run0_rich" != 1 ]; then
	log " VERDICT: run0 was not RICH. The model or the stack is wrong, nothing else counts."
elif [ "$got" = 0 ]; then
	log " VERDICT: no later runs captured. The test did not execute."
elif [ "$differed" = "$got" ]; then
	log " VERDICT: the vendor RECOMPUTES on every warm submit. A different input"
	log "  gives different output with no reset in between, which is exactly what"
	log "  rocket fails to do. The asymmetry is REAL."
elif [ "$differed" = 0 ]; then
	log " VERDICT: the vendor output NEVER CHANGED despite a different input every"
	log "  run. It does not recompute warm either, so this is normal behaviour for"
	log "  this block, and the 2026-07-16 conclusion was an artefact of feeding the"
	log "  same input five times. Look at what the runtime does between inferences."
else
	log " VERDICT: mixed, $differed of $got differed. Read the per-RUN lines."
fi
log "==============================================================="
# persist outputs on the SD so they can be pulled and scored vs golden.npy offline
cp -f "$OUT"/out_run0.bin "$CAPDIR/exp_run0.bin" 2>/dev/null
cp -f "$OUT"/out_run1.bin "$CAPDIR/exp_run1.bin" 2>/dev/null
cp -f "$OUT"/out_run2.bin "$CAPDIR/exp_run2.bin" 2>/dev/null
cp -f "$OUT"/out_run3.bin "$CAPDIR/exp_run3.bin" 2>/dev/null
cp -f "$OUT"/out_run4.bin "$CAPDIR/exp_run4.bin" 2>/dev/null
cp -f "$OUT/pc/out_run0.bin" "$CAPDIR/exp_pc.bin" 2>/dev/null
log "===== DONE (outputs copied to $CAPDIR/out_run*.bin for offline scoring) ====="
sync