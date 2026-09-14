#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The correction to what v10's cover said about Igor Paunovic's differential.
#
# IT REPLIES TO THE COVER, NOT TO HIM, AND THAT IS THE POINT. The false
# sentence is in the v10 cover on lore; a correction that only reaches his
# mailbox leaves the archive saying he reproduced something he reported he
# could not. In-Reply-To puts it under the message that carries the claim.
# The body also names the 27 August mail, which is the other instance.
#
# DRY=1 prints the headers and sends nothing. --confirm=never means git asks
# nobody anything, so this is the only way to see them first.
set -euo pipefail
cd "$(dirname "$0")"
M=reply-igor-correction.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }

# THE THREAD IS WHAT MAKES IT A CORRECTION RATHER THAN A NEW CLAIM.
grep -q '^In-Reply-To: <20260831040804\.24111-1-gahing@gahingwoo\.com>' "$M" || {
	echo "$M does not reply to the v10 cover" >&2; exit 1; }

# EVERY NUMBER IN IT IS HIS, READ OFF HIS OWN MESSAGE. If the mail ever
# stops carrying them it has drifted back towards the thing it retracts.
for s in '12 + 8 + 12 + 13 = 45' '48/48 on both arms' \
         'did not manifest in the 45' 'uniform 128' 'not' ; do
	grep -qF "$s" "$M" || { echo "$M no longer says: $s" >&2; exit 1; }
done

# AND IT MUST STILL QUOTE THE CLAIM IT RETRACTS, or a reader cannot tell
# what was withdrawn.
for s in '102 induced resets' '48 channels 0x80'; do
	grep -qF "$s" "$M" || { echo "$M no longer quotes: $s" >&2; exit 1; }
done

if grep -q '\*\*\*' "$M"; then echo "$M still carries a *** marker" >&2; exit 1; fi

n=$(awk 'NR>8 && length>72' "$M" | wc -l)
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
# THE RECIPIENTS ARE FLAGS, NOT HEADERS. --suppress-cc=all drops the Cc the
# file carries as well as the ones git harvests.
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
"${CMD[@]}" 2>&1 | tee /tmp/reply-correction-send.log
