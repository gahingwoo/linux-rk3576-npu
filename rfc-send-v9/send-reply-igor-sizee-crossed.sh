#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Round 336: SIZE_E_1 crossed with the channel count WITH a same-round control
# at every N, which round 285 did not have. Inert at 24, 32, 40, 48, 56 and 64;
# NOT inert at 16, where upstream's 0 halves the output. Also corrects two
# things this reply nearly went out with: that the sweep had not been run when
# it had, and a floor(n/16)*16 shortfall blamed on this field when it belongs to
# a different setting of the channel count register.
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
    reply-igor-sizee-crossed.eml
