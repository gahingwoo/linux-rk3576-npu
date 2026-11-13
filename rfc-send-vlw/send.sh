#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# One reply: reply-vlw.eml on v16 09/16, to Vladimir Bely's report of the
# probe-time hang on boards without the NPU enabled (2026-11-13).
#
#   DRY=1 ./send.sh   headers only, nothing is sent
#   YES=1 ./send.sh   sends it
set -euo pipefail
cd "$(dirname "$0")"
LOG=send.log
die() { echo "!! $*" >&2; exit 1; }

LISTS=(--cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
       --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
       --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
       --cc='linux-kernel@vger.kernel.org')
PEOPLE=(--cc='royalnet026@gmail.com' --cc='abel.vesa@oss.qualcomm.com'
        --cc='sebastian.reichel@collabora.com' --cc='sidong.yang@furiosa.ai'
        --cc='u.kleine-koenig@baylibre.com' --cc='chaoyi.chen@rock-chips.com'
        --cc='diederik@cknow-tech.com' --cc='alchark@flipper.net' --cc='leonard@lausen.nl'
        --cc='jeff.hugo@oss.qualcomm.com' --cc='rfoss@kernel.org')

# Reply-all to Vladimir: the v16 To, with him in front, plus Ulf's current
# address, Finley and Shawn Lin, who reviewed the pmdomain patches.
TO=(--to='vlwwwwww@gmail.com' --to='ulf.hansson@oss.qualcomm.com' --to='heiko@sntech.de'
    --to='finley.xiao@rock-chips.com' --to='tomeu@tomeuvizoso.net'
    --to='robh@kernel.org' --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org'
    --to='joro@8bytes.org' --to='will@kernel.org' --to='robin.murphy@arm.com'
    --to='ulfh@kernel.org' --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')
CC=(--cc='shawn.lin@rock-chips.com' "${PEOPLE[@]}" "${LISTS[@]}")

F=reply-vlw.eml
grep -q '^In-Reply-To: <20261113132323.159015-1-vlwwwwww@gmail.com>' $F ||
	die "$F does not answer Vladimir's mail"
if grep -qP '[^\x00-\x7F]' "$F"; then grep -nP '[^\x00-\x7F]' "$F" | head -3 >&2; die "$F has non-ASCII bytes"; fi
awk 'length > 76 && !/^(Subject|In-Reply-To|References|From):/ && !/^https?:/' "$F" | grep -q . &&
	die "$F has a line over 76 columns"

if [ "${DRY:-0}" = 1 ]; then
	git send-email --dry-run --confirm=never "${TO[@]}" "${CC[@]}" $F
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send, or DRY=1 to look"
git send-email --confirm=never "${TO[@]}" "${CC[@]}" $F 2>&1 | tee "$LOG"
grep -q "Result: 250" "$LOG" || die "the reply did not go out"
