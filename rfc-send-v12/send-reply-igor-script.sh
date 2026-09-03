#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The script Igor asked for on 2026-09-02 10:02, in the v9 05/13 thread:
#
#   "Yes, please send it. One honest note first: there is no vendor .rknn on
#    this disk [...] I will try to collect files produced by other toolkit
#    versions and point the script at those."
#
# The mail is a short cover and then rfc-send-v10/reserved0-build.py itself,
# the file that printed every number in the 2026-08-31 table, with one change:
# its default directory was a path on this machine and is now the current
# directory. Nothing else in it moved, and build-reply-igor-script.sh is what
# assembles the mail so the copy in it cannot drift from the file.
#
# ⚠ DRY=1 prints the headers and sends nothing. There is no other way to see
# them: --confirm=never means git asks nobody anything.
set -euo pipefail
cd "$(dirname "$0")"
M=reply-igor-script.eml
[ -s "$M" ] || { echo "$M is missing or empty" >&2; exit 1; }
# ⚠ THE SCRIPT HAS TO BE IN IT, whole. The cover promises a runnable file;
# a mail with the cover and no script, or a truncated one, posts a promise.
grep -q '^if __name__ == "__main__":' "$M" || {
	echo "$M does not end in the script's main guard -- the script is missing or cut" >&2
	exit 1; }
grep -q '^#!/usr/bin/env python3' "$M" || {
	echo "$M has no script shebang line" >&2; exit 1; }
# the cover, above the script, stays under 78 columns; the script is a file
# and keeps its own lines
cover_end=$(grep -n '^#!/usr/bin/env python3' "$M" | head -1 | cut -d: -f1)
n=$(awk -v e="$cover_end" 'NR>4 && NR<e && length>78' "$M" | wc -l)
[ "$n" = 0 ] || { echo "$n cover lines are over 78 columns" >&2; exit 1; }
# ⚠ NOTHING INVISIBLE AND NOTHING OUTSIDE ASCII: a mail with a zero-width
# character in it may not go through, and this one carries a script.
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$M" >/dev/null 2>&1; then
	echo "$M carries invisible Unicode; refusing" >&2; exit 1
fi
if grep -qP '[^\x00-\x7F]' "$M"; then
	echo "$M has non-ASCII bytes:" >&2; grep -nP '[^\x00-\x7F]' "$M" | head -3 >&2; exit 1
fi
echo "$M: $(wc -l <"$M") lines, cover $((cover_end - 1)) lines, script from line $cover_end"
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
"${CMD[@]}" 2>&1 | tee /tmp/reply-igor-script-send.log
