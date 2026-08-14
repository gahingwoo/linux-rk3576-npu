#!/usr/bin/env bash
# Reply to Alexey Charkov's RFC v2 patch-6 review, threaded under his message.
set -euo pipefail
cd "$(dirname "$0")"

echo "----- reply preview -----"; cat reply-alexey.eml; echo "-------------------------"
echo "To : alchark@flipper.net"
echo "Cc : tomeu, heiko, chaoyi.chen, dri-devel, linux-rockchip, linux-kernel"
echo "Threaded under: CAKTNdwHL2Z3h-FN7LLPshz5B0duiMw_pyfe=VG4UDhfm8igZ6Q@mail.gmail.com"
read -rp "Send this reply now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never \
  --to='alchark@flipper.net' \
  --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
  --cc='chaoyi.chen@rock-chips.com' \
  --cc='dri-devel@lists.freedesktop.org' \
  --cc='linux-rockchip@lists.infradead.org' \
  --cc='linux-kernel@vger.kernel.org' \
  reply-alexey.eml
echo "reply sent."
