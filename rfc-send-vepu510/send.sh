#!/usr/bin/env bash
# Send [RFC PATCH 0/3] media: rockchip: VEPU510 H.264 encoder for RK3576.
# One confirm gate, then git send-email (it will prompt for the SMTP password).
# Same style as ../rfc-send/send-v2.sh. From: Jiaxing Hu <gahing@gahingwoo.com>.
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/vepu510-rfc-send.log

# Maintainers (get_maintainer.pl) + Nicolas Dufresne (Collabora, Rockchip
# codec / hantro / the person most likely to recognize the inter-frame stall).
TO=(--to='mchehab@kernel.org' --to='heiko@sntech.de'
    --to='robh@kernel.org' --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org'
    --to='nicolas.dufresne@collabora.com')
CC=(--cc='ezequiel@vanguardiasur.com.ar'
    --cc='linux-media@vger.kernel.org' --cc='devicetree@vger.kernel.org'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

echo "Send [RFC PATCH 0/3] (cover + 3 patches), From: Jiaxing Hu <gahing@gahingwoo.com>"
echo "  To : mchehab, heiko, robh, krzk+dt, conor+dt, nicolas.dufresne"
echo "  Cc : ezequiel + linux-media, devicetree, linux-rockchip, linux-arm-kernel, linux-kernel"
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" \
  0000-cover-letter.patch 0001-*.patch 0002-*.patch 0003-*.patch \
  2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
if [[ -n "$CID" ]]; then
  echo
  echo "cover Message-Id: $CID"
  echo "lore: https://lore.kernel.org/all/$CID/"
fi
