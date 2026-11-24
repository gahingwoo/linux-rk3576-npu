#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send [PATCH v18 0/8] accel/rocket: RK3576 NPU (RKNN) enablement, on
# next-20261120. The pmdomain half was applied by Ulf, so pd/ is NOT sent.
# Generated from branch v18-npu in ~/Desktop/linux-next-v8; what is on disk
# is what was checked.
#
#   DRY=1 ./send-v18.sh    headers only, nothing is sent
#   YES=1 ./send-v18.sh    sends npu/
set -euo pipefail
cd "$(dirname "$0")"
LOG=send.log
die() { echo "!! $*" >&2; exit 1; }

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='p.zabel@pengutronix.de'
    --to='ogabbay@kernel.org' --to='zhangqing@rock-chips.com')
CC=(--cc='ddrake@baylibre.com'             # Daniel Drake, reviewed v17 4,8-12
    --cc='royalnet026@gmail.com'           # Igor Paunovic, Reviewed-by 1/8
    --cc='sidong.yang@furiosa.ai'          # Sidong Yang, Tested-by 1/8, RK3588
    --cc='ulf.hansson@oss.qualcomm.com'    # Ulf Hansson, applied the pmdomain half
    --cc='abel.vesa@oss.qualcomm.com'      # Abel Vesa, reviewed v16
    --cc='sebastian.reichel@collabora.com' # Sebastian Reichel, Rockchip
    --cc='chaoyi.chen@rock-chips.com'      # Chaoyi Chen, the PC_TASK_CON layout
    --cc='shawn.lin@rock-chips.com'        # Shawn Lin, Rockchip
    --cc='finley.xiao@rock-chips.com'      # Finley Xiao, Rockchip
    --cc='diederik@cknow-tech.com'         # Diederik de Haas, tested earlier versions
    --cc='alchark@flipper.net'             # Alexey Charkov, reviewed v2
    --cc='leonard@lausen.nl'               # Leonard Lausen, runs the series on a NanoPi M5
    --cc='vlwwwwww@gmail.com'              # Vladimir Bely, runs the series on a NanoPi R76S
    --cc='jeff.hugo@oss.qualcomm.com'      # Jeff Hugo, accel
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='devicetree@vger.kernel.org'
    --cc='linux-arm-kernel@lists.infradead.org' --cc='linux-kernel@vger.kernel.org')

C=npu/v18-0000-cover-letter.patch
[ -f "$C" ] || die "no cover"
n=$(ls npu/v18-000[1-8]-*.patch | wc -l); [ "$n" = 8 ] || die "expected 8 patches, found $n"
[ "$(ls npu/*.patch | wc -l)" = 9 ] || die "stray files in npu/"

if grep -n 'SUBJECT HERE\|BLURB HERE\|PLACEHOLDER\|TEST ONLY\|IOMMU patch lore link' npu/*.patch; then
	die "unwritten text (above)"
fi
grep -q '20261123235154.315460-1-gahing@gahingwoo.com' "$C" || die "the cover does not link the iommu fix"
grep -q '^base-commit: 909ef7a9a30fa139e69e555e3606680f5cca7726' "$C" || die "not on next-20261120"

ID=$(grep -m1 '^Message-ID:' "$C" | sed 's/.*<\(.*\)>.*/\1/')
[ "$(grep -l "^In-Reply-To: <$ID>" npu/v18-000[1-8]-*.patch | wc -l)" = 8 ] || die "not all patches reply to the cover"

for f in npu/v18-000[1-8]-*.patch; do
	grep -q '^Signed-off-by: Jiaxing Hu <gahing@gahingwoo.com>' "$f" || die "$f is not signed off"
	if awk '/^Subject/{s=1} /^---$/{exit} s && /^#/' "$f" | grep -q .; then die "$f has a '#' line in its message"; fi
done
grep -q '^Reviewed-by: Krzysztof Kozlowski' npu/v18-0002-*.patch || die "2/8 lost Krzysztof's Reviewed-by"
grep -q '^Acked-by: Conor Dooley' npu/v18-0003-*.patch || die "3/8 lost Conor's Acked-by"
grep -q '^Tested-by: Sidong Yang' npu/v18-0001-*.patch || die "1/8 lost Sidong's Tested-by"
if grep -l '^Tested-by: Sidong' npu/v18-000[4-6]-*.patch; then die "a rewritten patch still carries Sidong's Tested-by"; fi
if grep -l 'pmdomain: rockchip' npu/v18-000[1-8]-*.patch | grep -v 0008; then die "a pmdomain patch is in npu/"; fi

CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
for f in npu/*.patch; do
	if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$f" >/dev/null 2>&1; then die "$f carries invisible Unicode"; fi
	if grep -qP '[^\x00-\x7F]' "$f"; then grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2; die "$f has non-ASCII bytes"; fi
done

if [ "${DRY:-0}" = 1 ]; then
	git send-email --dry-run --confirm=never --suppress-cc=all "${TO[@]}" "${CC[@]}" npu/v18-*.patch
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send, or DRY=1 to look"
git send-email --confirm=never --suppress-cc=all "${TO[@]}" "${CC[@]}" npu/v18-*.patch 2>&1 | tee "$LOG"
[ "$(grep -c 'Result: 250' "$LOG")" = 9 ] || die "not all 9 went out; see $LOG"
