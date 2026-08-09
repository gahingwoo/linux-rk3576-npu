#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Distinct byte count, checksum and a sample of a buffer.

where.py reports how many bytes are NONZERO, which is the wrong question for
"did a memset knob fire": 0x7f is nonzero and so is almost every real weight, so
a buffer forced to one value and a buffer of real weights both come back at
100 percent. Round 8 used where.py as the control for ROCKET_PW_WTEST and
therefore verified nothing. This reports distinct, which does discriminate.

Usage: bstat.py <file.bin> [more.bin ...]
"""
import hashlib
import sys

for path in sys.argv[1:]:
    data = open(path, "rb").read()
    distinct = len(set(data))
    md5 = hashlib.md5(data).hexdigest()[:12]
    head = " ".join(f"{b:02x}" for b in data[:12])
    print(f"  {path.split('/')[-1]}: {len(data)} bytes  distinct={distinct}  "
          f"md5={md5}", flush=True)
    print(f"    first 12: {head}", flush=True)
