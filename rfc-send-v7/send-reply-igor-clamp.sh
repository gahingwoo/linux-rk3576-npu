#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Reply to Igor's RK3588 clamp measurement. His row plus the vendor userspace
# row on RK3576 put the same silicon on both sides of the question, so the
# clamp is the driver's.
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
    reply-igor-clamp.eml
