#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Two replies in the v6 7/9 subthread, both overdue: Chaoyi Chen gave the
# authoritative PC_TASK_CON field layout for RK3576 and RK3588 on 2026-08-10,
# and Igor Paunovic found a real leak in rocket_core_init() on 2026-08-08.
#
# Same recipient set as the v6 posting, so the replies land in the same
# threads for everyone who has been following them.
set -euo pipefail
cd "$(dirname "$0")"

TO=(--to='chaoyi.chen@rock-chips.com' --to='royalnet026@gmail.com'
    --to='heiko@sntech.de' --to='tomeu@tomeuvizoso.net'
    --to='robin.murphy@arm.com' --to='diederik@cknow-tech.com')
CC=(--cc='alchark@flipper.net'
    --cc='linux-rockchip@lists.infradead.org'
    --cc='dri-devel@lists.freedesktop.org'
    --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

git send-email --confirm=never "${TO[@]}" "${CC[@]}" \
	reply-chaoyi-taskcon.eml 2>&1 | tee /tmp/reply-chaoyi.log

git send-email --confirm=never "${TO[@]}" "${CC[@]}" \
	reply-igor-leak.eml 2>&1 | tee /tmp/reply-igor.log
