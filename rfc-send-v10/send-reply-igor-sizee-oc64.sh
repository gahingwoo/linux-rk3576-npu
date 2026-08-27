#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Reply to Igor Paunovic: the missing --notes, oc = 64 -> SIZE_E_2 = 1, and the
# SIZE_E question from 20 August answered from the 94 vendor models on disk.
#
# In-Reply-To is his message on v9 05/13, the one that caught the note.
set -euo pipefail
cd "$(dirname "$0")"
MSG=reply-igor-sizee-oc64.eml
IRT='<CANLpTt=ay-igor-v9-05-13@mail.gmail.com>'   # ⚠ REPLACE: real Message-Id

echo "Reply to Igor Paunovic"
echo "  file: $MSG   ($(wc -l < $MSG) lines)"
echo "  in-reply-to: $IRT"
echo
grep -q 'REPLACE' <<<"$IRT" 2>/dev/null && {
	echo "⚠ set IRT to the Message-Id of the mail you are answering first." >&2
	echo "   lore: https://lore.kernel.org/all/cover.1787568658.git.gahing@gahingwoo.com/" >&2
	exit 1; }
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }
git send-email --confirm=never --in-reply-to="$IRT" \
	--to='royalnet026@gmail.com' \
	--cc='linux-rockchip@lists.infradead.org' \
	--cc='dri-devel@lists.freedesktop.org' \
	"$MSG"
