#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The RESERVED_0 table Igor asked for on 2026-08-27 17:48:
#
#   "Yes, please send the RESERVED_0 table. A constant that follows the model
#    series rather than the geometry smells like a toolkit setting, and the
#    table is the way to corner it."
#
# ⚠ IT CORNERS OUR OWN CLAIM. The mail leads with the retraction: RESERVED_0
# follows neither the model series nor the geometry, all 94 files carry one
# toolkit build string, one file carries both values, and there is a third
# value we never mentioned. What it does follow is DPU 0x4044, 364 of 364.
# Sending a table fitted to the number we already published would have been
# the worse outcome by a distance.
#
# ⚠ DRY=1 prints the headers and sends nothing. There is no other way to see
# them: --confirm=never means git asks nobody anything.
set -euo pipefail
cd "$(dirname "$0")"

M=reply-igor-reserved0.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }

# ⚠ THE TABLE HAS TO BE IN IT. The mail is the header block plus
# reserved0-table.md; if the concatenation ever silently produced only the
# prose, this would post a retraction with no evidence behind it.
grep -q "^What it does follow" "$M" || {
	echo "$M has no table in it -- the concatenation lost it" >&2; exit 1; }
grep -q "364 of 364" "$M" || {
	echo "$M is missing the 0x4044 result, which is the whole answer" >&2
	exit 1; }
n=$(awk 'NR>4 && length>78' "$M" | wc -l)
[ "$n" = 0 ] || { echo "$n body lines are over 78 columns" >&2; exit 1; }

echo "$M: $(wc -l <"$M") lines, longest body line $(awk 'NR>4{print length}' "$M" | sort -rn | head -1)"
echo "In-Reply-To: $(sed -n 's/^In-Reply-To: //p' "$M")"
echo

CMD=(git send-email --confirm=never
    --to='royalnet026@gmail.com'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='dri-devel@lists.freedesktop.org'
    --no-thread --suppress-cc=all "$M")

if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	"${CMD[@]}" --dry-run
	exit 0
fi

echo "This posts to Igor, linux-rockchip and dri-devel. DRY=1 shows the headers."
read -rp "Send now? [y/N] " a
[[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }
"${CMD[@]}" 2>&1 | tee /tmp/reply-reserved0-send.log
