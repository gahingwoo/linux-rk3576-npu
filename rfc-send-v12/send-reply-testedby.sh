#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The Tested-by on Igor's core-removal patch, ON THE PATCH.
#
# ⚠ IT ALREADY EXISTS IN THE DVFS THREAD AND THAT IS THE POINT. Igor asked for
# it here on 2026-09-05: a tag in another thread is not under the patch, so b4
# will not collect it when Tomeu applies, and Igor reposting it on our behalf
# reads as a from/email mismatch. Same tag, same test, correct thread.
#
# ⚠ DRY=1 prints the headers and sends nothing. --confirm=never means git asks
# nobody anything, so this is the only way to see them first.
set -euo pipefail
cd "$(dirname "$0")"
M=reply-igor-testedby.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }

# ⚠ THE THREAD IS THE WHOLE REASON THIS MAIL EXISTS. If it lands anywhere but
# under the patch it is the same tag in the same wrong place as before.
grep -q '^In-Reply-To: <20260904125936\.26234-1-royalnet026@gmail\.com>' "$M" || {
	echo "$M does not reply to Igor's core-removal PATCH" >&2; exit 1; }
grep -q '^Subject: Re: \[PATCH\] accel/rocket: search every core slot' "$M" || {
	echo "$M does not carry the patch's subject" >&2; exit 1; }

# ⚠ EVERY NUMBER IN IT IS A PROMISE. These are the ones the board measured on
# 2026-09-04; if the mail ever stops carrying them the mail has drifted.
for s in 'Tested-by: Jiaxing Hu' 'two cores' 'bound: 2'; do
	grep -qF "$s" "$M" || { echo "$M no longer says: $s" >&2; exit 1; }
done

if grep -q '\*\*\*' "$M"; then echo "$M still carries a *** marker" >&2; exit 1; fi

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
    --to='royalnet026@gmail.com'
    --cc='tomeu@tomeuvizoso.net'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='dri-devel@lists.freedesktop.org'
    --no-thread --suppress-cc=all "$M")
if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	"${CMD[@]}" --dry-run
	exit 0
fi
echo "This posts to Igor, Tomeu, linux-rockchip and dri-devel."
read -rp "Send now? [y/N] " a
[[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }
"${CMD[@]}" 2>&1 | tee /tmp/reply-testedby-send.log
