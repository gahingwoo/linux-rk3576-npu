#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Split a board log into entries and print one row per entry.

Why this exists. Four readings in the 0x4050 and clamp threads were wrong the
same way: a value was grepped out of a few hundred lines by line number and
attached to the entry above or below the one it belonged to. The affine fit that
sent round 236 chasing a factor of sixteen actually belonged to the falsifier two
entries later. That is not a judgement error, it is a process error, and greping
a long log by hand is the process.

An entry starts at a "  -- <model>   <env>" line and ends at the next one. Every
number printed here comes from inside one entry's own block.

Usage: readlog.py <log> [--full]
"""
import re
import sys

FIELDS = [
    ("match",  r"channels match \(maxdiff <= 1\)", r"out\([^)]*\): (\d+)/(\d+) channels match"),
    ("npu",    r"npu distinct=", r"npu distinct=(\d+) min=(-?\d+) max=(-?\d+)"),
    ("unclamped", r"vs UNCLAMPED cpu", r"vs UNCLAMPED cpu: (\d+)/(\d+)"),
    ("clamped",   r"vs max\(cpu,zp\)", r"vs max\(cpu,zp\) : (\d+)/(\d+)"),
    ("slope",  r"a median", r"a median ([0-9.]+)"),
    ("b",      r"b median", r"b median ([+-][0-9.]+)"),
    ("maxdiff", r"maxdiff excluding", r"whole surface: (\d+)"),
]


def main():
    lines = open(sys.argv[1], errors="replace").read().splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("  -- ")]
    if not starts:
        print("no entries in this log")
        return
    starts.append(len(lines))

    print(f"{'model':<26} {'env':<44} {'match':>9} {'npu min..max':>14} "
          f"{'dist':>5} {'uncl':>8} {'clamp':>8} {'slope':>7} {'maxd':>5}")
    for a, b in zip(starts, starts[1:]):
        head = lines[a][5:].rstrip()
        parts = head.split(None, 1)
        model = parts[0]
        env = parts[1].strip() if len(parts) > 1 else ""
        block = "\n".join(lines[a:b])
        got = {}
        for name, marker, pat in FIELDS:
            m = re.search(pat, block)
            got[name] = m.groups() if m else None
        match = "/".join(got["match"]) if got["match"] else "-"
        npu = (f"{got['npu'][1]}..{got['npu'][2]}" if got["npu"] else "-")
        dist = got["npu"][0] if got["npu"] else "-"
        uncl = "/".join(got["unclamped"]) if got["unclamped"] else "-"
        clamp = "/".join(got["clamped"]) if got["clamped"] else "-"
        slope = got["slope"][0] if got["slope"] else "-"
        maxd = got["maxdiff"][0] if got["maxdiff"] else "-"
        print(f"{model:<26} {env:<44} {match:>9} {npu:>14} {dist:>5} "
              f"{uncl:>8} {clamp:>8} {slope:>7} {maxd:>5}")
        if "--full" in sys.argv:
            for l in lines[a:b]:
                if re.search(r"timed out|Page fault|SError|error", l):
                    print(f"      ! {l.strip()[:100]}")


main()
