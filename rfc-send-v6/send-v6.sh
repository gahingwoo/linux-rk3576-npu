#!/usr/bin/env bash
# Send [RFC PATCH v6 0/9] accel/rocket: RK3576 NPU (RKNN) enablement.
# Recipients from scripts/get_maintainer.pl over all 8 patches, plus everyone
# who has reviewed any version of this series.
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/v6-send.log

# Maintainers and reviewers per get_maintainer.pl.
# zhangqing is in-file maintainer of rockchip,power-controller.yaml (patch 2).
# joro/will/robin are here because patch 3 touches rockchip,iommu.yaml.
TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')

# Everyone who has reviewed or tested any version of this series.
CC=(--cc='royalnet026@gmail.com'          # Igor Paunovic, RK3588 Tested-by on v3
    --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2 patch 6
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, reviewed v1
    --cc='diederik@cknow-tech.com'        # Diederik de Haas, asked for the v5 split
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

echo "Send [RFC PATCH v6 0/9], From: Jiaxing Hu <gahing@gahingwoo.com>"
printf '  To : %s\n' "${TO[@]#--to=}"
printf '  Cc : %s\n' "${CC[@]#--cc=}"
echo "  Bcc: gahing@gahingwoo.com (from git config)"
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" \
  v6-0000-cover-letter.patch v6-0001-*.patch v6-0002-*.patch v6-0003-*.patch \
  v6-0004-*.patch v6-0005-*.patch v6-0006-*.patch v6-0007-*.patch v6-0008-*.patch v6-0009-*.patch \
  2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
if [[ -n "$CID" ]]; then
  echo "$CID" > /tmp/v6-cover-msgid.txt
  echo
  echo "v6 cover Message-Id: $CID"
  echo "lore: https://lore.kernel.org/all/$CID/"
else
  echo "WARN: could not capture cover Message-Id."
fi
