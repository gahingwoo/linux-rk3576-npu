#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Tell Igor his patch is being carried inside v11, before he sees it as 01/14.
#
# Tomeu asked for the bundling on the v10 cover: Sashiko will not review a
# series whose dependency is a prerequisite-patch-id it cannot follow. That is
# a good reason to bundle and no reason at all to do it quietly -- the patch is
# Igor's, he is active on this series, and he may want to send a v3 himself.
#
# ⚠ THE TAGS ARE THE PART THAT COULD GO WRONG, and the check for them belongs
# in send-v11.sh, not here. Our tree's copy carried only our own Reviewed-by,
# picked up before the others arrived, so bundling it as held would have
# posted his patch stripped of three reviews. That is our bookkeeping and not
# his problem, so the mail does not confess it -- send-v11.sh refuses to send
# a 01/14 that has lost any of the three, which is the guard that matters.
#
# ⚠ DRY=1 prints the headers and sends nothing.
set -euo pipefail
cd "$(dirname "$0")"

M=reply-igor-bundling.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }
# ⚠ MATCH ON SHORT STRINGS. A guard that greps a whole sentence fails the
# moment the mail is rewrapped at 78 columns, and it did: "should not have
# been sitting in my RFC" was present and split across a newline, and the
# check reported it missing minutes before sending.
for want in "under your name" "01/14" "Tomeu"; do
	grep -q "$want" "$M" || {
		echo "$M no longer mentions \"$want\" -- the point of the mail" >&2
		exit 1; }
done
n=$(awk 'NR>4 && length>78' "$M" | wc -l)
[ "$n" = 0 ] || { echo "$n body lines over 78 columns" >&2; exit 1; }

CMD=(git send-email --confirm=never
    --to='royalnet026@gmail.com'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='dri-devel@lists.freedesktop.org'
    --cc='tomeu@tomeuvizoso.net'
    --no-thread --suppress-cc=all "$M")

if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	"${CMD[@]}" --dry-run
	exit 0
fi
echo "This posts to Igor, Tomeu, linux-rockchip and dri-devel."
read -rp "Send now? [y/N] " a
[[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }
"${CMD[@]}" 2>&1 | tee /tmp/reply-bundling-send.log
