#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# OFF-LIST, to Igor only. He sent the generator and the scorer off-list on the
# 17th because it is ten kilobytes of Python and the lists do not need it, and
# asked whether to post them. This answers that, and carries what his tool
# found: the parity form of 0x4050 confirmed at seven output channel counts
# where the modulo form disagrees, instead of the one shape it rested on.
set -euo pipefail
cd "$(dirname "$0")"

git send-email --confirm=never \
    --to='royalnet026@gmail.com' \
    --no-thread --suppress-cc=all \
    reply-igor-generator.eml
