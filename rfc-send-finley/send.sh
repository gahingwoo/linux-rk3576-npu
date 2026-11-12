#!/bin/bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Two replies, sent in this order:
#   reply-finley.eml  on v16 10/16, to Finley Xiao's review (2026-11-11)
#   reply-ulf.eml     on v15 00/15, to Ulf's "Patch 7, 9 and 10 applied"
#
#   DRY=1 ./send.sh   headers only, nothing is sent
#   YES=1 ./send.sh   sends both
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

# Reply-all to Finley: his To, minus me, with him in front.
TO_F=(--to='finley.xiao@rock-chips.com' --to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de'
      --to='robh@kernel.org' --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org'
      --to='joro@8bytes.org' --to='will@kernel.org' --to='robin.murphy@arm.com'
      --to='ulfh@kernel.org' --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
      --to='zhangqing@rock-chips.com')
CC_F=("${PEOPLE[@]}" --cc='shawn.lin@rock-chips.com' "${LISTS[@]}")

# Reply-all to Ulf, plus Finley and Shawn Lin, since it points at Finley's mail.
TO_U=(--to='ulf.hansson@oss.qualcomm.com' --to='heiko@sntech.de')
CC_U=(--cc='finley.xiao@rock-chips.com' --cc='shawn.lin@rock-chips.com'
      --cc='tomeu@tomeuvizoso.net' --cc='robh@kernel.org' --cc='krzk+dt@kernel.org'
      --cc='conor+dt@kernel.org' --cc='joro@8bytes.org' --cc='will@kernel.org'
      --cc='robin.murphy@arm.com' --cc='ulfh@kernel.org' --cc='p.zabel@pengutronix.de'
      --cc='ogabbay@kernel.org' --cc='zhangqing@rock-chips.com' "${PEOPLE[@]}" "${LISTS[@]}")

grep -q '^In-Reply-To: <ca90a994-70cc-410a-902d-5c4c0aacc9b7@rock-chips.com>' reply-finley.eml ||
	die "reply-finley.eml does not answer Finley's 10/16 mail"
grep -q '^In-Reply-To: <CAPx+jO_gRtipR7iuh0D7G2Wi25GZoqFD1JHVbJNmhd1UyC3Bmg@mail.gmail.com>' reply-ulf.eml ||
	die "reply-ulf.eml does not answer Ulf's applied mail"
for f in reply-finley.eml reply-ulf.eml; do
	if grep -qP '[^\x00-\x7F]' "$f"; then grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2; die "$f has non-ASCII bytes"; fi
	awk 'length > 76 && !/^(Subject|In-Reply-To|References|From):/ && !/^https?:/' "$f" | grep -q . &&
		die "$f has a line over 76 columns"
done

if [ "${DRY:-0}" = 1 ]; then
	git send-email --dry-run --confirm=never "${TO_F[@]}" "${CC_F[@]}" reply-finley.eml
	git send-email --dry-run --confirm=never "${TO_U[@]}" "${CC_U[@]}" reply-ulf.eml
	exit 0
fi
[ "${YES:-0}" = 1 ] || die "set YES=1 to send, or DRY=1 to look"
git send-email --confirm=never "${TO_F[@]}" "${CC_F[@]}" reply-finley.eml 2>&1 | tee "$LOG"
grep -q "Result: 250" "$LOG" || die "the reply to Finley did not go out; the reply to Ulf is NOT sent"
git send-email --confirm=never "${TO_U[@]}" "${CC_U[@]}" reply-ulf.eml 2>&1 | tee -a "$LOG"
