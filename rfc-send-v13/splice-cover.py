#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# format-patch --cover-letter writes *** SUBJECT HERE *** and *** BLURB HERE ***,
# so regenerating the series throws the cover letter away. The subject and the
# body live outside the generated file and are put back here, which is what lets
# send-v10.sh regenerate as often as it likes.
import sys

SUBJECT = "accel/rocket: RK3576 NPU (RKNN) enablement"

cover, blurb = sys.argv[1], sys.argv[2]
s = open(cover).read()
if "*** SUBJECT HERE ***" not in s or "*** BLURB HERE ***" not in s:
    sys.exit("%s has no placeholders; refusing to splice" % cover)
s = s.replace("*** SUBJECT HERE ***", SUBJECT, 1)
s = s.replace("*** BLURB HERE ***", open(blurb).read().rstrip("\n"), 1)
open(cover, "w").write(s)
