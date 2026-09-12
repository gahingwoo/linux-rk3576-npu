#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The reply to Igor's 2026-09-12 correction of his own reports.
#
# ⚠ IT GOES UNDER 03/14, NOT THE COVER. He replied to the patch, and the
# changes he asks for are that patch's commit message and tag. A reply in the
# cover thread is the same misplacement the Tested-by had on v11.
#
# ⚠ DRY=1 prints the headers and sends nothing.
set -euo pipefail
cd "$(dirname "$0")"
M=reply-igor-0x80.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }

# ⚠ THE THREAD IS THE POINT, so both ends of it are checked.
grep -q '^In-Reply-To: <20260912113717\.6819-1-royalnet026@gmail\.com>' "$M" || {
	echo "$M does not reply to Igor's 09-12 correction" >&2; exit 1; }
grep -q '20260912065053\.1519165-4-gahing@gahingwoo\.com' "$M" || {
	echo "$M does not reference v12 03/14" >&2; exit 1; }
grep -q '^Subject: Re: \[PATCH v12 03/14\]' "$M" || {
	echo "$M does not carry 03/14's subject" >&2; exit 1; }

# ⚠ EVERY COMMITMENT IN IT IS A PROMISE ABOUT v13. If the mail stops saying
# one of these, the mail has drifted from what v13 will actually do.
for s in 'Igor also ran a differential on' \
         'His own bound on it is the right one' \
         '45 induced resets on 19 August, 102 on 25 August and 74 today' \
         'differential base' \
         'JOB_TIMEOUT_MS=2'; do
	grep -qF "$s" "$M" || { echo "$M no longer says: $s" >&2; exit 1; }
done

if grep -q '\*\*\*' "$M"; then echo "$M still carries a *** marker" >&2; exit 1; fi

n=$(awk 'NR>11 && length>72' "$M" | wc -l)
[ "$n" = 0 ] || { echo "$n body lines are over 72 columns" >&2; exit 1; }

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
# ⚠ RECIPIENTS ARE FLAGS, NOT HEADERS -- --suppress-cc=all drops the ones git
# would harvest as well as any the file carries.
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
"${CMD[@]}" 2>&1 | tee /tmp/reply-igor-0x80-send.log
