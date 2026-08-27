#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send [PATCH v10 00/13] accel/rocket: RK3576 NPU (RKNN) enablement.
#
# To and Cc are scripts/get_maintainer.pl over all thirteen patches, which
# returns exactly the v8 set, plus the reviewers who are not in it and whose
# v8 comments this version answers.
#
# ⚠ NEW SINCE v8: Uwe Kleine-Koenig, who asked for the narrower device-id
# header on v8 10/12 and is not in the maintainer list for anything the series
# touches. 11/13 answers him and he should see it.
#
# ⚠⚠ --notes IS NOT OPTIONAL. v9's cover letter said 05/13 carried a git note
# naming the base and the one prerequisite, and the posted mail had no Notes
# section: this script's v9 ancestor never passed --notes, so the note in the
# repository was simply not emitted. Igor caught it on the thread on 25 August
# and Rob's bot had asked for the dependency on v8. Regenerate here rather than
# trusting whatever is in the directory.
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/v10-send.log

REGEN=${REGEN:-1}
TREE=${TREE:-$HOME/Desktop/linux-next-v8}
if [ "$REGEN" = 1 ]; then
	rm -f v10-0*.patch
	git -C "$TREE" format-patch --notes -v10 --cover-letter \
	    -o "$PWD" d589af989..v10-prep >/dev/null
	for f in 0*.patch; do [ -e "$f" ] && mv "$f" "v10-$f"; done
	n=$(grep -lc '^Notes:' v10-*.patch 2>/dev/null | wc -l)
	[ "$n" = 1 ] || { echo "expected exactly one patch with a Notes block, got $n" >&2; exit 1; }
	echo "regenerated $(ls v10-0*.patch | wc -l) patches, Notes block on:"
	grep -l '^Notes:' v10-*.patch | sed 's/^/  /'
fi

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')

CC=(--cc='royalnet026@gmail.com'          # Igor Paunovic, Tested-by 1/13, Reviewed-by 4/13
    --cc='u.kleine-koenig@baylibre.com'   # Uwe Kleine-Koenig, the header on 11/13
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, confirmed the PC_TASK_CON layout
    --cc='diederik@cknow-tech.com'        # Diederik de Haas, the iommu binding
    --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

echo "Send [PATCH v10 00/13], From: Jiaxing Hu <gahing@gahingwoo.com>"
printf '  To : %s\n' "${TO[@]#--to=}"
printf '  Cc : %s\n' "${CC[@]#--cc=}"
echo
ls v10-00*.patch | sed 's/^/  /'
echo
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" v10-*.patch 2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
[[ -n "$CID" ]] && echo && echo "lore: https://lore.kernel.org/all/$CID/"
