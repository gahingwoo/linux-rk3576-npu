#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Asking Tomeu how he wants the RK3576 work in rocket submitted. Not a patch
# post: Mesa takes merge requests, so this is only the question that decides
# what shape the series should be.
set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='tomeu@tomeuvizoso.net' \
    --cc='royalnet026@gmail.com' \
    --cc='alchark@gmail.com' \
    --no-thread --suppress-cc=all \
    tomeu-rk3576.eml
