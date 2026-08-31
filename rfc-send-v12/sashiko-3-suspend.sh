#!/bin/sh
# Does the NPU core actually suspend? -- the premise 04/14 rests on.
#
# 04/14 ("let the core suspend after a reset") replaces pm_runtime_put_noidle()
# with pm_runtime_put_autosuspend() so the domain can power off and, on the way
# back on, 10/14 pulses the domain's resets. Sashiko's objection is that
# autosuspend is ASYNCHRONOUS: the delay is 50 ms, rocket_reset() calls
# drm_sched_start() immediately after, and a resubmit takes a PM reference and
# cancels the pending suspend. If that is right the domain never cycles, 10/14
# never fires, and all that actually happens is rocket_core_reset() pulsing the
# core's own resets.
#
# This does NOT induce a timeout -- JOB_TIMEOUT_MS is a #define, so that needs a
# kernel rebuild and a flash. It asks the cheaper question first, which is
# whether this hardware suspends AT ALL under a real workload, because if it
# does not then the reset path cannot be relying on it either.
#
# Everything here is read-only apart from running charsiu.
set -u

BIN=${CHARSIU_BIN_DIR:-/opt/charsiu}
MODELS=${CHARSIU_MODELS:-$HOME/.charsiu/models}
[ -d "$MODELS" ] || MODELS=/opt/charsiu/models

say() { printf '\n=========== %s ===========\n' "$*"; }
FAIL=0
bad() { printf '  !! %s\n' "$*"; FAIL=$((FAIL + 1)); }
ok()  { printf '  ok %s\n' "$*"; }

say "the cores runtime PM sysfs presents"
NPUS=""
for d in /sys/bus/platform/devices/*/; do
	[ -e "$d/of_node/compatible" ] || continue
	if tr -d '\0' <"$d/of_node/compatible" | grep -q "rknn-core"; then
		NPUS="$NPUS $d"
	fi
done
if [ -z "$NPUS" ]; then
	bad "no rknn-core platform device found; nothing to measure"
	exit 1
fi
for d in $NPUS; do
	printf '  %s\n' "$(basename "$d")"
	for f in control runtime_status autosuspend_delay_ms \
		 runtime_active_time runtime_suspended_time; do
		[ -r "$d/power/$f" ] && \
		    printf '      %-24s %s\n' "$f" "$(cat "$d/power/$f")"
	done
done

# ⚠ THE DELAY IS THE WHOLE ARGUMENT. rocket_core_init() sets 50 ms; if this
# board reports something else the reasoning above has to be redone against
# whatever it actually says rather than against the source.
for d in $NPUS; do
	dly=$(cat "$d/power/autosuspend_delay_ms" 2>/dev/null || echo "?")
	[ "$dly" = 50 ] || bad "$(basename "$d") autosuspend delay is $dly ms, not the 50 the driver sets"
done

say "does it suspend at all, under a real decode"
M=""
for f in "$MODELS"/*Q4_0*.gguf; do [ -r "$f" ] && M=$f && break; done
if [ -z "$M" ]; then
	bad "no Q4_0 model under $MODELS"
else
	printf '  model %s\n' "$(basename "$M")"
	for d in $NPUS; do
		b=$(basename "$d")
		s0=$(cat "$d/power/runtime_suspended_time" 2>/dev/null || echo 0)
		a0=$(cat "$d/power/runtime_active_time" 2>/dev/null || echo 0)
		eval "s0_$(echo "$b" | tr -c 'a-zA-Z0-9' _)=$s0"
		eval "a0_$(echo "$b" | tr -c 'a-zA-Z0-9' _)=$a0"
	done
	env CHARSIU_NPU=1 CHARSIU_NPU_QUANT=1 CHARSIU_NPU_W4V=1 \
	    CHARSIU_NPU_KMAX=1024 CHARSIU_NPU_W4_GROUP=1024 \
	    CHARSIU_NPU_MAXN=262144 CHARSIU_COEF_ELEMS=65536 \
	    "$BIN/charsiu_run" "$M" -p "hello" -n 24 --ignore-eos \
	    >/dev/null 2>&1
	for d in $NPUS; do
		b=$(basename "$d"); k=$(echo "$b" | tr -c 'a-zA-Z0-9' _)
		s1=$(cat "$d/power/runtime_suspended_time" 2>/dev/null || echo 0)
		a1=$(cat "$d/power/runtime_active_time" 2>/dev/null || echo 0)
		eval "ds=\$((s1 - \$s0_$k)); da=\$((a1 - \$a0_$k))"
		printf '  %-28s active +%s ms   suspended +%s ms\n' "$b" "$da" "$ds"
		# ⚠ ZERO SUSPENDED TIME IS THE INTERESTING ANSWER, not an error.
		# It says the gaps between submits never reach the 50 ms delay,
		# which is exactly the condition under which 04/14's put cannot
		# take effect after a reset either.
		if [ "$ds" -eq 0 ]; then
			printf '      never suspended during the run -- so a submit that\n'
			printf '      follows a reset inside 50 ms would not either\n'
		fi
	done
fi

say "has a timeout ever happened, and did a suspend follow it"
# ⚠ dmesg ONLY. Nothing here induces a timeout: JOB_TIMEOUT_MS is a #define, so
# forcing one needs a rebuilt kernel and a flash, and this board's NPU has been
# recorded as not recovering from one -- which is the symptom 04/14 is supposed
# to remove and therefore not a thing to trigger casually mid round.
n=$(dmesg 2>/dev/null | grep -c "NPU job timed out" || echo 0)
printf '  "NPU job timed out" in dmesg: %s\n' "$n"
if [ "$n" -gt 0 ]; then
	dmesg | grep -A 3 "NPU job timed out" | tail -12 | sed 's/^/      /'
	printf '\n  Read the suspended_time above against this: a timeout that was\n'
	printf '  followed by no suspended time is 04/14 not taking effect.\n'
else
	ok "none, so this boot says nothing about the reset path"
fi

say "verdict"
if [ "$FAIL" -eq 0 ]; then
	printf '  nothing contradicted the driver source.\n'
else
	printf '  %s check(s) disagreed with the source; see above.\n' "$FAIL"
fi
printf '\n  What settles 04/14 is a kernel with JOB_TIMEOUT_MS lowered, a job\n'
printf '  induced to time out, and a submit issued immediately after. That is a\n'
printf '  build and a flash, so it is deliberately not what this script does.\n'
