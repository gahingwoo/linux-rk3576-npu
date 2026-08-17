#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Reply to Tomeu with the pushed branch, plus the one correction to the numbers
# in the first mail. To Tomeu only, no cc.
set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='tomeu@tomeuvizoso.net' \
    --no-thread --suppress-cc=all \
    reply-tomeu-branch.eml
