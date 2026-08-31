#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Reply to Igor on v9 05/13, the mail where he noticed the missing Notes
# section: send-v9.sh never passed --notes. Also the oc = 64 answer owed since
# the 17th and his SIZE_E question from the 20th, both settled from the 94
# compiled vendor .rknn already on disk.

# ⚠⚠ ALREADY SENT. 2026-08-27 13:49 +1200, SMTP result 250, recorded in
# SENT.md with its Message-ID. Running this again posts a DUPLICATE to Igor,
# linux-rockchip and dri-devel.
#
# It had no prompt, no preview and no dry run -- invoking it sent. And its
# name sits next to send-v10.sh under tab completion, where `./send-r<TAB>`
# completes straight to it. That is one keystroke between auditing a series
# and re-posting a month-old reply to two public lists.
if [ "${RESEND:-0}" != 1 ]; then
	echo "this reply was already sent on 2026-08-27 (see SENT.md)." >&2
	echo "RESEND=1 overrides, and there is no reason to." >&2
	exit 1
fi

set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='royalnet026@gmail.com' \
    --cc='linux-rockchip@lists.infradead.org' \
    --cc='dri-devel@lists.freedesktop.org' \
    --no-thread --suppress-cc=all \
    reply-igor-sizee-oc64.eml
