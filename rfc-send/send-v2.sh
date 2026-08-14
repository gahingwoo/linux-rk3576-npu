#!/usr/bin/env bash
# Send [RFC PATCH v2 0/8] accel/rocket: RK3576 NPU (RKNN) enablement.
# One confirm gate, then git send-email (it will prompt for the SMTP password).
# Captures the cover Message-Id so send-reply-chaoyi.sh can link to it.
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/v2-send.log

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org')
CC=(--cc='chaoyi.chen@rock-chips.com'
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

echo "Send [RFC PATCH v2 0/8] (cover + 8 patches), From: Jiaxing Hu <gahing@gahingwoo.com>"
echo "  To : tomeu, heiko, robh, krzk+dt, conor+dt, joro, will, robin.murphy, ulfh, p.zabel, ogabbay"
echo "  Cc : chaoyi.chen + dri-devel, linux-rockchip, iommu, linux-pm, devicetree, linux-arm-kernel, linux-kernel"
echo "  Bcc: gahing@gahingwoo.com (from git config)"
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" \
  v2-0000-cover-letter.patch v2-0001-*.patch v2-0002-*.patch v2-0003-*.patch \
  v2-0004-*.patch v2-0005-*.patch v2-0006-*.patch v2-0007-*.patch v2-0008-*.patch \
  2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
if [[ -n "$CID" ]]; then
  echo "$CID" > /tmp/v2-cover-msgid.txt
  echo
  echo "v2 cover Message-Id: $CID"
  echo "lore: https://lore.kernel.org/all/$CID/"
  echo "Next: ./send-reply-chaoyi.sh   (replies to Chaoyi with this link)"
else
  echo "WARN: could not capture cover Message-Id; fill the v2 link into reply-chaoyi.eml by hand."
fi
