#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send the single rockchip-iommu patch, on next-20261120 (rockchip-iommu.c
# is the same there as in v7.4-rc4). Generated from branch iommu-banks in
# ~/Desktop/linux-next-v8; what is on disk is what was checked.
#
#   DRY=1 ./send.sh    headers only, nothing is sent
#   YES=1 ./send.sh    sends it
set -euo pipefail
cd "$(dirname "$0")"
LOG=send.log
die() { echo "!! $*" >&2; exit 1; }

TO=(--to='joro@8bytes.org' --to='will@kernel.org' --to='robin.murphy@arm.com'
    --to='heiko@sntech.de')
CC=(--cc='tomeu@tomeuvizoso.net'          # Tomeu Vizoso, rocket, the NPU driver that hits this
    --cc='ddrake@baylibre.com'            # Daniel Drake, reviewing rocket
    --cc='sidong.yang@furiosa.ai'         # Sidong Yang, tests rocket on RK3588 (two-bank NPU MMUs)
    --cc='anton.sovetov@gmail.com'        # Anton Sovetov, RFC on the same file
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, Rockchip
    --cc='iommu@lists.linux.dev' --cc='linux-rockchip@lists.infradead.org'
    --cc='linux-arm-kernel@lists.infradead.org' --cc='linux-kernel@vger.kernel.org')

P=(0001-*.patch)
[ ${#P[@]} = 1 ] && [ -f "${P[0]}" ] || die "expected exactly one patch"
f=${P[0]}
grep -q '^Signed-off-by: Jiaxing Hu <gahing@gahingwoo.com>' "$f" || die "not signed off"
grep -q '^Fixes: cd6438c5f844 ' "$f" || die "Fixes tag missing"
grep -q '^base-commit: ' "$f" || die "no base-commit"
if awk '/^Subject/{s=1} /^---$/{exit} s && /^#/' "$f" | grep -q .; then die "a '#' line in the message"; fi
if grep -n 'PLACEHOLDER\|TEST ONLY\|\*\*\*' "$f"; then die "unwritten or test-only text (above)"; fi
if grep -qP '[^\x00-\x7F]' "$f"; then grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2; die "non-ASCII bytes"; fi
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$f" >/dev/null 2>&1; then die "invisible Unicode"; fi

if [ "${DRY:-0}" = 1 ]; then
	git send-email --dry-run --confirm=never --suppress-cc=all "${TO[@]}" "${CC[@]}" "$f"
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send, or DRY=1 to look"
git send-email --confirm=never --suppress-cc=all "${TO[@]}" "${CC[@]}" "$f" 2>&1 | tee "$LOG"
[ "$(grep -c 'Result: 250' "$LOG")" = 1 ] || die "not sent; see $LOG"
