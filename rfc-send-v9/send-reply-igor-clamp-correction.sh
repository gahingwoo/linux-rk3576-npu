#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The clamp correction. The 88 and 120 sweep and the reference argument were
# already sent, on the 17th and the 14th, and the first draft of this mail
# announced both as news. What is left is the correction and the tension the
# vendor's own 0x40ac creates with it.
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
    reply-igor-0x4050-sweep.eml
