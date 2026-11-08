#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send [PATCH v16 00/16] accel/rocket: RK3576 NPU (RKNN) enablement, and the
# two replies on v15 that go with it (reply-tomeu.eml, reply-heiko.eml).
#
# The patches are generated from branch v16-wip in ~/Desktop/linux-next-v8,
# on next-20261105. They are not regenerated here: what is on disk is what
# was checked, and what is on disk is what goes.
#
#   DRY=1 ./send-v16.sh    headers only, nothing is sent
#   YES=1 ./send-v16.sh    sends the series, then the two replies
set -euo pipefail
cd "$(dirname "$0")"
LOG=send.log

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')

CC=(--cc='royalnet026@gmail.com'          # Igor Paunovic, author of 1/16, tags on 2,3,5/16
    --cc='abel.vesa@oss.qualcomm.com'     # Abel Vesa, Reviewed-by 9/16 and 10/16
    --cc='sebastian.reichel@collabora.com' # Sebastian Reichel, Reviewed-by 1/16
    --cc='sidong.yang@furiosa.ai'         # Sidong Yang, Tested-by 1/16
    --cc='u.kleine-koenig@baylibre.com'   # Uwe Kleine-Koenig, the header on 11/16
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, the PC_TASK_CON layout, 11/16 comment
    --cc='shawn.lin@rock-chips.com'       # Shawn Lin, Rockchip, reviewed the QoS fix
    --cc='finley.xiao@rock-chips.com'     # Finley Xiao, Rockchip, reviewed the QoS fix
    --cc='diederik@cknow-tech.com'        # Diederik de Haas, Tested-by 1/16
    --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2
    --cc='leonard@lausen.nl'              # Leonard Lausen, runs v14 on a NanoPi M5
    --cc='jeff.hugo@oss.qualcomm.com'     # Jeff Hugo, accel, blamed_fixes
    --cc='rfoss@kernel.org'               # Robert Foss, blamed_fixes
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

die() { echo "!! $*" >&2; exit 1; }

# Sixteen patches and a cover, nothing else.
np=$(ls v16-00[0-9][0-9]-*.patch | grep -vc -- '-0000-' || true)
[ "$np" = 16 ] || die "expected 16 patches, found $np"
[ -f v16-0000-cover-letter.patch ] || die "no cover letter"
[ -f reply-tomeu.eml ] && [ -f reply-heiko.eml ] || die "a reply is missing"

# The QoS fix went out on its own on 2026-11-01 and must not ride along.
if grep -l 'do not restore QoS that was never saved' v16-*.patch >/dev/null 2>&1; then
	die "the QoS fix is in this series; it was sent separately"
fi

# 1/16 is Igor's, with his name and every tag it has collected.
grep -q '^From: Igor Paunovic' v16-0001-*.patch || die "1/16 is not authored by Igor Paunovic"
for t in 'Sidong Yang' 'Diederik de Haas' 'Sebastian Reichel' 'Heiko Stuebner'; do
	grep -q "$t" v16-0001-*.patch || die "1/16 has lost $t's tag"
done

# No draft markers, no Notes, no prerequisite-patch-id, one base-commit.
if grep -n '\*\*\*' v16-0000-cover-letter.patch; then die "the cover still has a *** marker"; fi
n=$(grep -l '^Notes:' v16-*.patch 2>/dev/null | wc -l || true)
[ "$n" = 0 ] || die "a Notes block is on $n patch(es)"
q=$(grep -l '^prerequisite-patch-id:' v16-*.patch 2>/dev/null | wc -l || true)
[ "$q" = 0 ] || die "prerequisite-patch-id is on $q patch(es)"
grep -q '^base-commit: ' v16-0000-cover-letter.patch || die "no base-commit on the cover"

# The replies answer specific mails.
grep -q '^In-Reply-To: <20261104125529.3229301-1-tomeu@tomeuvizoso.net>' reply-tomeu.eml ||
	die "reply-tomeu.eml does not answer Tomeu's 3/15 mail"
grep -q '^In-Reply-To: <3654048.cLl3JjQhRp@diego>' reply-heiko.eml ||
	die "reply-heiko.eml does not answer Heiko's 3/15 mail"

# No invisible Unicode, no non-ASCII.
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
for f in v16-*.patch reply-*.eml; do
	if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$f" >/dev/null 2>&1; then
		die "$f carries invisible Unicode"
	fi
	if grep -qP '[^\x00-\x7F]' "$f"; then
		grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2
		die "$f has non-ASCII bytes"
	fi
done

echo "Send $(sed -n 's/^Subject: //p' v16-0000-cover-letter.patch | head -1)"
echo "     then reply-tomeu.eml and reply-heiko.eml"
printf '  To : %s\n' "${TO[@]#--to=}"
printf '  Cc : %s\n' "${CC[@]#--cc=}"
ls v16-00*.patch | sed 's/^/  /'

if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	git send-email --dry-run --confirm=never "${TO[@]}" "${CC[@]}" v16-*.patch
	git send-email --dry-run --confirm=never "${TO[@]}" "${CC[@]}" reply-tomeu.eml reply-heiko.eml
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send for real (19 messages), or DRY=1 to look"

git send-email --confirm=never "${TO[@]}" "${CC[@]}" v16-*.patch 2>&1 | tee "$LOG"
CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
[ -n "$CID" ] || die "no Message-Id in $LOG; the replies are NOT sent"
echo "lore: https://lore.kernel.org/all/$CID/"

git send-email --confirm=never "${TO[@]}" "${CC[@]}" reply-tomeu.eml reply-heiko.eml 2>&1 | tee -a "$LOG"
