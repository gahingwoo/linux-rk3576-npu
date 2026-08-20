#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
set -euo pipefail
cd "$(dirname "$0")"
git send-email --confirm=never \
    --to='u.kleine-koenig@baylibre.com' \
    --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
    --cc='royalnet026@gmail.com' --cc='chaoyi.chen@rock-chips.com' \
    --cc='dri-devel@lists.freedesktop.org' \
    --cc='linux-rockchip@lists.infradead.org' \
    --cc='linux-arm-kernel@lists.infradead.org' \
    --cc='linux-kernel@vger.kernel.org' \
    --no-thread --suppress-cc=all reply-uwe-devicetable.eml
