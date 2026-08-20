#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
set -euo pipefail
cd "$(dirname "$0")"
git send-email --confirm=never \
    --to='robh@kernel.org' \
    --cc='krzysztof.kozlowski@oss.qualcomm.com' --cc='conor+dt@kernel.org' \
    --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
    --cc='devicetree@vger.kernel.org' \
    --cc='dri-devel@lists.freedesktop.org' \
    --cc='linux-rockchip@lists.infradead.org' \
    --cc='linux-kernel@vger.kernel.org' \
    --no-thread --suppress-cc=all reply-rob-dtcheck.eml
