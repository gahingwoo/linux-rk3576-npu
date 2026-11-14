#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send v17 as two series, in this order:
#   pd/   [PATCH v17 0/3]  pmdomain: rockchip: RK3576 NPU domain supply and
#         settle delay, on Ulf's next (844a13010b0b), to Ulf
#   npu/  [PATCH v17 00/12] accel/rocket: RK3576 NPU (RKNN) enablement, on
#         next-20261113
#
# The two covers link to each other by Message-ID; the IDs are fixed in the
# files, so they are known before sending.
#
# The patches were generated from branches v17-pd and v17-npu in
# ~/Desktop/linux-next-v8. They are not regenerated here: what is on disk is
# what was checked, and what is on disk is what goes.
#
#   DRY=1 ./send-v17.sh    headers only, nothing is sent
#   YES=1 ./send-v17.sh    sends pd/, then npu/
set -euo pipefail
cd "$(dirname "$0")"
LOG=send.log
die() { echo "!! $*" >&2; exit 1; }

LISTS_PD=(--cc='linux-pm@vger.kernel.org' --cc='linux-rockchip@lists.infradead.org'
          --cc='linux-arm-kernel@lists.infradead.org' --cc='linux-kernel@vger.kernel.org')
TO_PD=(--to='ulf.hansson@oss.qualcomm.com' --to='ulfh@kernel.org' --to='heiko@sntech.de')
CC_PD=(--cc='finley.xiao@rock-chips.com'      # Finley Xiao, reviewed v16 9/16, 10/16, 14/16
       --cc='shawn.lin@rock-chips.com'        # Shawn Lin, Rockchip pmdomain
       --cc='sebastian.reichel@collabora.com' # Sebastian Reichel, Rockchip pmdomain
       --cc='vlwwwwww@gmail.com'              # Vladimir Bely, reported the hang 1/3 fixes
       --cc='leonard@lausen.nl'               # Leonard Lausen, DOMAIN_RK3576_R used by 2/3
       --cc='abel.vesa@oss.qualcomm.com'      # Abel Vesa, Reviewed-by v16 9/16
       --cc='tomeu@tomeuvizoso.net'           # Tomeu Vizoso, rocket, the other half
       "${LISTS_PD[@]}")

TO_NPU=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
        --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
        --to='will@kernel.org' --to='robin.murphy@arm.com' --to='p.zabel@pengutronix.de'
        --to='ogabbay@kernel.org' --to='zhangqing@rock-chips.com')
CC_NPU=(--cc='royalnet026@gmail.com'          # Igor Paunovic, author of 1/12, tags on 2,3,5/12
        --cc='ulf.hansson@oss.qualcomm.com'   # Ulf Hansson, the pmdomain half
        --cc='abel.vesa@oss.qualcomm.com'     # Abel Vesa, reviewed v16
        --cc='sebastian.reichel@collabora.com' # Sebastian Reichel, Reviewed-by 1/12
        --cc='sidong.yang@furiosa.ai'         # Sidong Yang, Tested-by 1/12
        --cc='u.kleine-koenig@baylibre.com'   # Uwe Kleine-Koenig, the header on 8/12
        --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, the PC_TASK_CON layout
        --cc='shawn.lin@rock-chips.com'       # Shawn Lin, Rockchip
        --cc='finley.xiao@rock-chips.com'     # Finley Xiao, Rockchip, reviewed v16
        --cc='diederik@cknow-tech.com'        # Diederik de Haas, Tested-by 1/12
        --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2
        --cc='leonard@lausen.nl'              # Leonard Lausen, runs the series on a NanoPi M5
        --cc='vlwwwwww@gmail.com'             # Vladimir Bely, runs the series on a NanoPi R76S
        --cc='jeff.hugo@oss.qualcomm.com'     # Jeff Hugo, accel
        --cc='rfoss@kernel.org'               # Robert Foss
        --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
        --cc='iommu@lists.linux.dev' --cc='devicetree@vger.kernel.org'
        --cc='linux-arm-kernel@lists.infradead.org' --cc='linux-kernel@vger.kernel.org')

# Counts.
n=$(ls pd/v17-000[1-9]-*.patch | wc -l); [ "$n" = 3 ] || die "pd/: expected 3 patches, found $n"
n=$(ls npu/v17-00[0-9][0-9]-*.patch | grep -vc -- '-0000-' || true)
[ "$n" = 12 ] || die "npu/: expected 12 patches, found $n"
[ -f pd/v17-0000-cover-letter.patch ] && [ -f npu/v17-0000-cover-letter.patch ] || die "a cover is missing"

# Nothing unwritten goes out.
if grep -n 'PLACEHOLDER\|\*\*\*\|@@[A-Z_]*@@' pd/*.patch npu/*.patch; then
	die "unwritten text is still in the series (lines above)"
fi

# 1/12 is Igor's, with every tag it has collected.
grep -q '^From: Igor Paunovic' npu/v17-0001-*.patch || die "1/12 is not authored by Igor Paunovic"
for t in 'Sidong Yang' 'Diederik de Haas' 'Sebastian Reichel' 'Heiko Stuebner' 'named the clock indices'; do
	grep -q "$t" npu/v17-0001-*.patch || die "1/12 has lost '$t'"
done

# The pmdomain fix carries its reporter; the delay patch its suggester.
grep -q '^Reported-by: Vladimir Bely' pd/v17-0001-*.patch || die "pd 1/3 has no Reported-by"
grep -q '^Suggested-by: Finley Xiao' pd/v17-0003-*.patch || die "pd 3/3 has no Suggested-by"

# Dropped patches stay dropped.
if grep -l 'cycle an optional power-domain reset\|allow resets in a power domain node\|add NPU core domain clocks and resets' pd/*.patch npu/*.patch; then
	die "a patch dropped in v17 is back"
fi

# Signed-off, no Notes, no prerequisite-patch-id, one base-commit per cover.
for f in pd/v17-000[1-9]-*.patch npu/v17-00[0-9][0-9]-*.patch; do
	case $f in *-0000-*) continue;; esac
	grep -q '^Signed-off-by: Jiaxing Hu <gahing@gahingwoo.com>' "$f" || die "$f is not signed off"
done
n=$(grep -l '^Notes:\|^prerequisite-patch-id:' pd/*.patch npu/*.patch 2>/dev/null | wc -l || true)
[ "$n" = 0 ] || die "Notes or prerequisite-patch-id on $n file(s)"
grep -q '^base-commit: 844a13010b0b' pd/v17-0000-cover-letter.patch || die "pd/ is not on Ulf's next 844a13010b0b"
grep -q '^base-commit: 84abb955b101' npu/v17-0000-cover-letter.patch || die "npu/ is not on next-20261113"

# Threads: each series replies to its own cover, the covers link each other.
PDID=$(grep -m1 '^Message-ID:' pd/v17-0000-cover-letter.patch | sed 's/.*<\(.*\)>.*/\1/')
NPUID=$(grep -m1 '^Message-ID:' npu/v17-0000-cover-letter.patch | sed 's/.*<\(.*\)>.*/\1/')
[ "$PDID" != "$NPUID" ] || die "the two covers share a Message-ID"
[ "$(grep -l "^In-Reply-To: <$PDID>" pd/v17-000[1-9]-*.patch | wc -l)" = 3 ] || die "pd/ patches do not all reply to the pd cover"
[ "$(grep -l "^In-Reply-To: <$NPUID>" npu/v17-00[0-9][0-9]-*.patch | wc -l)" = 12 ] || die "npu/ patches do not all reply to the npu cover"
grep -q "lore.kernel.org/all/$NPUID/" pd/v17-0000-cover-letter.patch || die "the pd cover does not link the npu cover"
grep -q "lore.kernel.org/all/$PDID/" npu/v17-0000-cover-letter.patch || die "the npu cover does not link the pd cover"
d=$(grep -h -m1 '^Message-ID' pd/*.patch npu/*.patch | sort | uniq -d | wc -l)
[ "$d" = 0 ] || die "$d Message-ID(s) repeat"

# No invisible Unicode, no non-ASCII.
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
for f in pd/*.patch npu/*.patch; do
	if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$f" >/dev/null 2>&1; then
		die "$f carries invisible Unicode"
	fi
	if grep -qP '[^\x00-\x7F]' "$f"; then grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2; die "$f has non-ASCII bytes"; fi
done

if [ "${DRY:-0}" = 1 ]; then
	git send-email --dry-run --confirm=never --suppress-cc=all "${TO_PD[@]}" "${CC_PD[@]}" pd/v17-*.patch
	git send-email --dry-run --confirm=never --suppress-cc=all "${TO_NPU[@]}" "${CC_NPU[@]}" npu/v17-*.patch
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send, or DRY=1 to look"
git send-email --confirm=never --suppress-cc=all "${TO_PD[@]}" "${CC_PD[@]}" pd/v17-*.patch 2>&1 | tee "$LOG"
[ "$(grep -c 'Result: 250' "$LOG")" = 4 ] || die "pd/ did not all go out; npu/ is NOT sent"
git send-email --confirm=never --suppress-cc=all "${TO_NPU[@]}" "${CC_NPU[@]}" npu/v17-*.patch 2>&1 | tee -a "$LOG"
[ "$(grep -c 'Result: 250' "$LOG")" = 17 ] || die "npu/ did not all go out; see $LOG"
