#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What does the vendor change from one ROW WINDOW to the next?

Round 60 located the depthwise error exactly. mesa splits a 112x112 stride-1
depthwise into two row-window tasks, 90 output rows then 22, and the row
maxdiff profile is

    dw_imp   1 1 1 1 1 1 1 1 1 1 1 1 200 200
    mn_dw1   1 1 1 1 1 1 1 1 1 1 1 1 255 255

sampled every eighth row. Rows 0 to 88 are within 1 of the reference, which is
rounding, and rows 96 and 104 are garbage. Task 0 covers output rows 0 to 89
and task 1 covers 90 to 111. So the depthwise ARITHMETIC is right, all of it,
and the second row window is wrong.

That also explains the whole shape of this investigation: every regular model
here is 80x80 or smaller and emits ONE task, which is why they are all perfect
and why every coefficient sweep came back flat.

The capture can say what a window is supposed to change, because the vendor
dispatches this same layer as six tasks. Diffing consecutive tasks of sv_dwu
gives the registers that carry the window, and diffing sv_rgu the same way
separates "this is what a window changes" from "this is what depthwise
changes".

⚠ The vendor spreads its six tasks over three subcores, two each, per the
capture's meta.txt. Ours run on one core. So the COUNT is not comparable and
only the per-window register deltas are.
"""
import os
import struct
import sys

from extract_regcmd import TARGETS, decode

ADDR_REGS = {0x1088, 0x1110, 0x4018, 0x5020, 0x5024, 0x100c}


def runs(path, min_run=40):
    d = open(path, "rb").read()
    n = len(d) // 8
    w = struct.unpack("<%dQ" % n, d[:n * 8])
    out, i = [], 0
    while i < n:
        if ((w[i] >> 48) & 0xffff) in TARGETS:
            j = i
            while j < n and ((w[j] >> 48) & 0xffff) in TARGETS:
                j += 1
            if j - i >= min_run:
                out.append([decode(w[k]) for k in range(i, j)])
            i = j
        else:
            i += 1
    return out


def as_map(entries):
    m = {}
    for tgt, val, reg in entries:
        m.setdefault((tgt, reg), val)
    return m


def report(root, tag):
    rs = runs(os.path.join(root, tag, "bo01.bin"))
    print(f"\n=== {tag}: {len(rs)} tasks ===")
    maps = [as_map(r) for r in rs]
    keys = sorted(set().union(*maps))
    moving = [k for k in keys
              if len({m.get(k) for m in maps}) > 1]
    print(f"  {len(moving)} registers move across the six tasks "
          f"({sum(1 for k in moving if k[1] in ADDR_REGS)} of them addresses)")
    for k in moving:
        vals = [m.get(k) for m in maps]
        if k[1] in ADDR_REGS:
            base = min(v for v in vals if v is not None)
            shown = ", ".join(f"+0x{v - base:05x}" for v in vals)
            print(f"    {TARGETS[k[0]]:5s} 0x{k[1]:04x}  base 0x{base:08x} "
                  f"then {shown}")
        else:
            print(f"    {TARGETS[k[0]]:5s} 0x{k[1]:04x}  "
                  + ", ".join(f"0x{v:08x}" for v in vals))


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    report(root, "sv_dwu")
    report(root, "sv_rgu")
