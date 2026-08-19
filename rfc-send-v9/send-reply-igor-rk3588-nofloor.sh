#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Igor measured RK3588 with no lift and found no floor, so the floor is RK3576
# specific. This declines his offer to read the vendor's A on RK3588, since
# there is nothing there to compensate, and says the measurement is ours.
set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='royalnet026@gmail.com' \
    --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
    --cc='chaoyi.chen@rock-chips.com' --cc='alchark@flipper.net' \
    --cc='dri-devel@lists.freedesktop.org' \
    --cc='linux-rockchip@lists.infradead.org' \
    --cc='linux-arm-kernel@lists.infradead.org' \
    --cc='linux-kernel@vger.kernel.org' \
    --no-thread --suppress-cc=all \
    reply-igor-rk3588-nofloor.eml
