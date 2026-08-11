#!/usr/bin/env bash
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
	reply-chaoyi-lastlayer.eml 2>&1 | tee /tmp/reply-chaoyi2.log
