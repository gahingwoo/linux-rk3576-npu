#!/usr/bin/env bash
# Reply to Chaoyi Chen's patch-4 comment, threaded under it, with the v2 lore link.
# Run AFTER send-v2.sh (it captures the v2 cover Message-Id).
set -euo pipefail
cd "$(dirname "$0")"

CID=$(cat /tmp/v2-cover-msgid.txt 2>/dev/null || true)
if [[ -n "$CID" ]]; then
  LINK="https://lore.kernel.org/all/$CID/"
else
  echo "No captured v2 cover Message-Id (run ./send-v2.sh first)."
  read -rp "Paste the v2 lore link (or leave blank to say 'posted to the list'): " LINK
  [[ -n "$LINK" ]] || LINK="(posted to the list)"
fi

tmp=$(mktemp /tmp/reply-chaoyi.XXXX.eml)
sed "s|__V2LINK__|$LINK|" reply-chaoyi.eml > "$tmp"
echo "----- reply preview -----"; cat "$tmp"; echo "-------------------------"
echo "To: chaoyi.chen@rock-chips.com  (Cc: tomeu, heiko, linux-rockchip, iommu)"
echo "Threaded under Chaoyi's patch-4 comment."
read -rp "Send this reply now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; rm -f "$tmp"; exit 1; }

git send-email --confirm=never \
  --to='chaoyi.chen@rock-chips.com' \
  --cc='tomeu@tomeuvizoso.net' --cc='heiko@sntech.de' \
  --cc='linux-rockchip@lists.infradead.org' --cc='iommu@lists.linux.dev' \
  "$tmp"
rm -f "$tmp"
echo "reply sent."
