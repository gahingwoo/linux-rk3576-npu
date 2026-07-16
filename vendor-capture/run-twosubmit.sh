#!/bin/sh
# ---------------------------------------------------------------------------
# VENDOR two-submit control (2026-07-16). The missing symmetric half of the
# rocket SPREAD-CONFIRM test.
#
# QUESTION: does the WORKING vendor stack re-arm on the 2nd (and later)
# INDEPENDENT submit within ONE power session (no genpd power-cycle)? Rocket
# does NOT (only op0 MACs per session). If the vendor ALSO degrades on submit 2,
# the walled state is NORMAL hardware behaviour (hypothesis CONFIRMED, per-op
# dispatch is a dead end -> must chain). If the vendor stays correct, rocket is
# missing a per-submit re-arm that is NOT a register write (already audited) =>
# ordering/timing/fence in the submit path.
#
# Model: exp2_rk3576.rknn (single conv, calibrated NON-saturating -> correct
# output is a RICH map, so an empty MAC = CONSTANT is unmistakable). Input is the
# flat byte ramp i%251. On the vendor, run0 is a known-good baseline (the vendor
# runs any model correctly); the decisive read is run1..run4.
#
# REGIME A: one context, rknn_run() x5 back-to-back (vendor's normal ctx reuse).
#           All 5 submits share ONE powered session (gaps are ms, autosuspend is
#           3s). run0 = known-good cold-start; run1..4 = the decisive read.
# REGIME B (power-cycle control): idle >3.5s so genpd powers the NPU domain DOWN
#           (rknpu power_put_delay = 3000ms), THEN one fresh submit = op0 of a
#           NEW power session -- must come back RICH, proving the session
#           boundary is what re-arms and the model itself is fine.
#
# VERDICT (printed to console):
#   run0 RICH + run1..RICH + all md5 equal  => vendor RE-ARMS per submit  => the
#        rocket gap is ordering/timing, not a writel. (refutes "wall is normal")
#   run0 RICH + run1.. CONSTANT/min==max, and post-idle submit RICH again
#        => only op0 per session MACs on the vendor too; the wall is NORMAL hw
#        behaviour and a power-cycle is the re-arm. Chain, don't spread. (confirms)
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

log "----- REGIME A md5 per run (equal across runs => identical output) -----"
for f in "$OUT"/out_run0.bin "$OUT"/out_run1.bin "$OUT"/out_run2.bin "$OUT"/out_run3.bin "$OUT"/out_run4.bin; do
	[ -e "$f" ] && md5sum "$f" > "$C" 2>&1
done

log ""
log "----- REGIME B: power-cycle control -- idle 4s (let genpd power OFF), then 1 fresh submit -----"
sleep 4
"$BIN" "$MODEL" 1 "$OUT/pc" 2>&1 | tee "$OUT/B.log" > "$C"
log "----- REGIME B: post-idle submit should be RICH again (new session op0 re-arms) -----"

# ---- compute the VERDICT on-board (no host scoring needed) ----
m0=$(md5sum "$OUT/out_run0.bin" 2>/dev/null | cut -d' ' -f1)
all_equal=1; got=0
for i in 1 2 3 4; do
	mi=$(md5sum "$OUT/out_run$i.bin" 2>/dev/null | cut -d' ' -f1)
	[ -n "$mi" ] && got=1
	[ "$mi" = "$m0" ] || all_equal=0
done
run0_rich=0; grep -q "RUN 0 .*RICH" "$OUT/A.log" && run0_rich=1
later_all_const=1
for i in 1 2 3 4; do grep -q "RUN $i .*RICH" "$OUT/A.log" && later_all_const=0; done
pc_rich=0; grep -q "RUN 0 .*RICH" "$OUT/B.log" && pc_rich=1

log ""
log "=========================== VERDICT ==========================="
if [ "$run0_rich" = 1 ] && [ "$all_equal" = 1 ] && [ "$got" = 1 ]; then
	log " VERDICT: vendor RE-ARMS per submit (run0..4 all RICH + byte-identical)."
	log "  => rocket's gap is TIMING/ORDERING, not a register (writel-audit already clean)."
	log "  => the walled state is NOT normal hw behaviour. Next: trace-diff a known-good"
	log "     2nd independent vendor submit vs rocket's failing one on this exact model."
elif [ "$run0_rich" = 1 ] && [ "$later_all_const" = 1 ]; then
	log " VERDICT: vendor ALSO WALLS on submit>=2 (run0 RICH, run1..4 CONSTANT/empty-MAC)."
	[ "$pc_rich" = 1 ] && log "  power-cycle control RICH => a genpd cycle re-arms; the model is fine."
	log "  => HYPOTHESIS CONFIRMED: only op0 per power session does real MACs on the vendor too."
	log "  => the wall is NORMAL hw behaviour. Per-op/SPREAD dispatch is a dead end -- CHAIN"
	log "     into one HW-iterated job (RK3588 next-pointer style), don't spread submits."
else
	log " VERDICT: MIXED/partial -- run0_rich=$run0_rich all_equal=$all_equal later_all_const=$later_all_const pc_rich=$pc_rich."
	log "  Inspect the per-RUN lines above (min/max + RICH/CONSTANT) and the md5s."
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