#!/bin/sh
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# DOES THE POWER DOMAIN CYCLE UNDER A REAL WORKLOAD -- measured on the DOMAIN.
#
# ⚠⚠ WHY THIS REPLACES sashiko-3-suspend.sh FOR THIS QUESTION. That script
# reads power/runtime_active_time and power/runtime_suspended_time, which are
# per DEVICE. Sashiko's objection on 4/14 is about the DOMAIN: if the gap
# between submits is shorter than the 50 ms autosuspend delay the domain does
# not cycle, 10/14's reset pulse on power-on never fires, and rocket_core_reset
# is all that runs. A device-level counter cannot answer that, and the cover
# answered it with one anyway.
#
# ⚠ The pair it answered with, 11.4 s active and 17.8 s suspended, has no
# surviving artifact anywhere in this tree. It appears in the cover letter and
# nowhere else. So this round exists to produce a number that can be pointed at.
#
# genpd exposes per-domain accounting under /sys/kernel/debug/pm_genpd. The
# layout differs between kernels, so both are handled: a per-domain directory
# with current_state/active_time/idle_time, and the single summary file.
#
set -u
W=${1:-}
[ -n "$W" ] || { echo "usage: $0 '<command to run under the measurement>'" >&2; exit 2; }

G=/sys/kernel/debug/pm_genpd
[ -d "$G" ] || { echo "no $G -- CONFIG_DEBUG_FS and CONFIG_PM_GENERIC_DOMAINS_OF" >&2; exit 2; }

# name state active_us idle_us, one line a domain, npu ones only
snap() {
	for d in "$G"/npu "$G"/nputop "$G"/npu0 "$G"/npu1; do
		n=$(basename "$d")
		if [ -d "$d" ]; then
			#
			# ⚠ THE FILE IS total_idle_time, NOT idle_time. Reading the
			# wrong name and defaulting to 0 prints a column that looks
			# like "the domain never idled" and is really "this script
			# asked for a file that is not there". `idle_states` carries
			# the COUNT of entries, which is the thing actually under
			# test: a domain that cycles has a usage count that grows.
			#
			printf '%-7s %-7s active %-12s idle %-12s downs %s\n' "$n" \
				"$(cat "$d/current_state" 2>/dev/null || echo '?')" \
				"$(cat "$d/active_time" 2>/dev/null || echo MISSING)" \
				"$(cat "$d/total_idle_time" 2>/dev/null || echo MISSING)" \
				"$(awk 'NR>1{n+=$3} END{print n+0}' "$d/idle_states" 2>/dev/null || echo MISSING)"
		fi
	done
	# the summary form, when there are no per-domain directories
	[ -d "$G/npu" ] || awk '/^(npu|nputop|npu0|npu1) /{print $1, $2, "-", "-"}' \
		"$G/pm_genpd_summary" 2>/dev/null
}

echo "== does the NPU domain cycle under a real workload"
echo "   boot id   $(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
echo "   dsu0      $(cat /sys/kernel/debug/clk/clk_rknn_dsu0/clk_rate 2>/dev/null) Hz"
echo "   autosusp  $(cat /sys/bus/platform/devices/*rknn*/power/autosuspend_delay_ms 2>/dev/null | head -1) ms"
echo
echo "-- before"
snap | sed 's/^/   /'

T0=$(awk '{printf "%d", $1*1000}' /proc/uptime)
sh -c "$W" >/dev/null 2>&1
T1=$(awk '{printf "%d", $1*1000}' /proc/uptime)

echo
echo "-- after ($((T1 - T0)) ms of wall clock in the workload)"
snap | sed 's/^/   /'
echo
#
# ⚠ A DOMAIN THAT NEVER LEFT `on` DURING THE RUN IS THE ANSWER SASHIKO
# EXPECTS, NOT A BROKEN MEASUREMENT. The claim under test is that it cycles;
# if active_time grew by the whole wall clock and idle_time did not move, it
# did not cycle, and 10/14's pulse did not fire. Report what happened either
# way -- the cover has already once reported the comfortable half of this.
#
echo "⚠ Read the DELTA, not the totals. idle_time growing across the run is the"
echo "  domain cycling; active_time growing by the whole wall clock with idle"
echo "  flat is the domain staying up, which is Sashiko's case and must be"
echo "  reported as such."
