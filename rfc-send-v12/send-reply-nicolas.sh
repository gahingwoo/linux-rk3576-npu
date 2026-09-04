#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The reply to Nicolas Dufresne in Igor's DVFS RFC thread: he removed the
# assigned clock and rate from his RK3588 DTS, and on RK3576 that rate is what
# keeps the block inside the voltage its rail is given.
#
# ⚠ DRY=1 prints the headers and sends nothing. --confirm=never means git asks
# nobody anything, so this is the only way to see them first.
set -euo pipefail
cd "$(dirname "$0")"
M=reply-nicolas-dts.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }

# ⚠ THE THREAD, OR IT IS A NEW ONE. lore has the parent as
# c495dae1976dab842d77f4a4a142217eb77b6fb7.camel@ndufresne.ca; without In-Reply-To this lands
# as an orphan and nobody reading the RFC sees it.
grep -q '^In-Reply-To: <c495dae1976dab842d77f4a4a142217eb77b6fb7\.camel@ndufresne\.ca>' "$M" || {
	echo "$M does not reply to Nicolas.s 2026-08-17 mail" >&2; exit 1; }
grep -q '^Subject: Re: \[RFC\] accel/rocket: DVFS on RK3588' "$M" || {
	echo "$M does not carry the thread's subject" >&2; exit 1; }

# ⚠ EVERY NUMBER IN IT IS A PROMISE. These are the ones the board measured on
# 2026-09-04; if the mail ever stops carrying them the mail has drifted.
for s in '786.432 MHz' 'load bearing' '11 to 25 wrong rows a pass' \
         '786 MHz, 800 mV'; do
	grep -qF "$s" "$M" || { echo "$M no longer says: $s" >&2; exit 1; }
done

# the body stays under 72 columns; the headers are git's business
n=$(awk 'NR>11 && length>72' "$M" | wc -l)
[ "$n" = 0 ] || { echo "$n body lines are over 72 columns" >&2; exit 1; }

# ⚠ NOTHING INVISIBLE AND NOTHING OUTSIDE ASCII in the body. The Cc header
# carries an RFC 2047 encoded name, which is ASCII on the wire by design.
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$M" >/dev/null 2>&1; then
	echo "$M carries invisible Unicode; refusing" >&2; exit 1
fi
if grep -qP '[^\x00-\x7F]' "$M"; then
	echo "$M has non-ASCII bytes:" >&2; grep -nP '[^\x00-\x7F]' "$M" | head -3 >&2; exit 1
fi

echo "$M: $(wc -l <"$M") lines"
echo "In-Reply-To: $(sed -n 's/^In-Reply-To: //p' "$M")"
echo
# ⚠ THE RECIPIENTS ARE FLAGS, NOT HEADERS. --suppress-cc=all drops the Cc the
# file carries as well as the ones git harvests: the first dry run of this
# addressed Igor alone and neither list. The previous reply in this thread
# passed them as flags for the same reason.
CMD=(git send-email --confirm=never
    --to='nicolas@ndufresne.ca'
    --cc='royalnet026@gmail.com'
    --cc='tomeu@tomeuvizoso.net'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='dri-devel@lists.freedesktop.org'
    --no-thread --suppress-cc=all "$M")
if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	"${CMD[@]}" --dry-run
	exit 0
fi
echo "This posts to Nicolas, Igor, Tomeu, linux-rockchip and dri-devel."
read -rp "Send now? [y/N] " a
[[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }
"${CMD[@]}" 2>&1 | tee /tmp/reply-nicolas-send.log
