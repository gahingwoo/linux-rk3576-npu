#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
TO=(--to='diederik@cknow-tech.com' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='tomeu@tomeuvizoso.net')
CC=(--cc='royalnet026@gmail.com' --cc='alchark@flipper.net'
    --cc='chaoyi.chen@rock-chips.com'
    --cc='iommu@lists.linux.dev' --cc='linux-rockchip@lists.infradead.org'
    --cc='devicetree@vger.kernel.org' --cc='dri-devel@lists.freedesktop.org'
    --cc='linux-arm-kernel@lists.infradead.org' --cc='linux-kernel@vger.kernel.org')
git send-email --confirm=never "${TO[@]}" "${CC[@]}" reply-diederik-iommu.eml 2>&1 | tee /tmp/reply-diederik.log
