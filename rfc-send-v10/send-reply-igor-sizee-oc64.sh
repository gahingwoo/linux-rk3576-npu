#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Reply to Igor on v9 05/13, the mail where he noticed the missing Notes
# section: send-v9.sh never passed --notes. Also the oc = 64 answer owed since
# the 17th and his SIZE_E question from the 20th, both settled from the 94
# compiled vendor .rknn already on disk.
set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='royalnet026@gmail.com' \
    --cc='linux-rockchip@lists.infradead.org' \
    --cc='dri-devel@lists.freedesktop.org' \
    --no-thread --suppress-cc=all \
    reply-igor-sizee-oc64.eml
