#!/usr/bin/env bash
# Correction to the v6 thread: the completion interrupt works, the poll should
# not exist, and the root cause is the PC_TASK_CON field layout.
set -euo pipefail
cd "$(dirname "$0")"
git send-email \
	--to='robin.murphy@arm.com' \
	--to='diederik@cknow-tech.com' \
	--to='tomeu@tomeuvizoso.net' \
	--to='heiko@sntech.de' \
	--cc='royalnet026@gmail.com' \
	--cc='alchark@flipper.net' \
	--cc='chaoyi.chen@rock-chips.com' \
	--cc='linux-rockchip@lists.infradead.org' \
	--cc='dri-devel@lists.freedesktop.org' \
	--cc='linux-arm-kernel@lists.infradead.org' \
	--cc='linux-kernel@vger.kernel.org' \
	--no-thread --suppress-cc=all --confirm=never \
	reply-interrupt-correction.eml
