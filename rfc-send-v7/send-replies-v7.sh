#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# The two v7 replies: Igor on 08/10 and Diederik on 04/10.
set -euo pipefail
cd "$(dirname "$0")"

COMMON_CC=(--cc='linux-rockchip@lists.infradead.org'
           --cc='linux-arm-kernel@lists.infradead.org'
           --cc='linux-kernel@vger.kernel.org')

# Igor, on the RK3576 patch: the stale comment, where the refactor goes,
# and the synchronize_irq question he asked on 1/10.
git send-email --confirm=never \
    --to='royalnet026@gmail.com' \
    --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
    --cc='chaoyi.chen@rock-chips.com' --cc='alchark@flipper.net' \
    --cc='dri-devel@lists.freedesktop.org' \
    "${COMMON_CC[@]}" \
    reply-igor-v7.eml 2>&1 | tee /tmp/reply-igor-v7.log

# Diederik, on the iommu binding: the new compatible, for real this time.
git send-email --confirm=never \
    --to='diederik@cknow-tech.com' \
    --cc='heiko@sntech.de' --cc='robh@kernel.org' \
    --cc='krzk+dt@kernel.org' --cc='conor+dt@kernel.org' \
    --cc='joro@8bytes.org' --cc='will@kernel.org' \
    --cc='robin.murphy@arm.com' --cc='tomeu@tomeuvizoso.net' \
    --cc='royalnet026@gmail.com' \
    --cc='iommu@lists.linux.dev' --cc='devicetree@vger.kernel.org' \
    "${COMMON_CC[@]}" \
    reply-diederik-v7.eml 2>&1 | tee /tmp/reply-diederik-v7.log
