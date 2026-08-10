#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
The depthwise register diff, with only `groups` moving.

Round 42 tried this with g_dw1 against g_k3s1 and got 41 differing registers,
which was useless: those two models differ in channel count, spatial size AND
in being depthwise, so nothing in the diff could be attributed. sv_dwu and
sv_rgu are ic = oc = 32 at 112x112, k = 3, s = 1, one calibration set each, and
the ONLY difference is `groups`. Whatever differs between their register
streams is what depthwise mode is.

Both streams come from the CAPTURE, not from the .rknn, so these are the values
that actually reached the hardware on a run that produced correct output.

Addresses are excluded from the verdict, not from the listing: every buffer
sits somewhere else in the two captures, so an address difference carries no
information about depthwise, and counting it would drown the diff.

DECISION RULE, written before the run:
  the two streams have the same length and the same register set, and a small
  number of non-address values differ  -> those values ARE depthwise mode, and
  each one is checked against what mesa writes
  a large diff  -> the two models were not compiled the way this assumes, and
  the pair has to be rebuilt before anything is read from it
"""
import os
import struct
import sys

from extract_regcmd import TARGETS, decode

ADDR_REGS = {0x1088, 0x1110, 0x4018, 0x5020, 0x5024, 0x5004, 0x3004, 0x1004,
             0x4004, 0x100c, 0x2004, 0x2008}


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
                out.append((i * 8, [decode(w[k]) for k in range(i, j)]))
            i = j
        else:
            i += 1
    return out


def as_map(entries):
    m = {}
    for tgt, val, reg in entries:
        m.setdefault((tgt, reg), []).append(val)
    return m


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    a = runs(os.path.join(root, "sv_rgu", "bo01.bin"))
    b = runs(os.path.join(root, "sv_dwu", "bo01.bin"))
    print(f"sv_rgu: {len(a)} runs   sv_dwu: {len(b)} runs")
    for i in range(min(len(a), len(b))):
        oa, ea = a[i]
        ob, eb = b[i]
        ma, mb = as_map(ea), as_map(eb)
        keys = sorted(set(ma) | set(mb))
        diffs, addrs, onlya, onlyb = [], [], [], []
        for k in keys:
            if k not in ma:
                onlyb.append(k)
            elif k not in mb:
                onlya.append(k)
            elif ma[k] != mb[k]:
                (addrs if k[1] in ADDR_REGS else diffs).append(k)
        print(f"\n=== task {i}: rgu@0x{oa:05x} {len(ea)} entries   "
              f"dwu@0x{ob:05x} {len(eb)} entries ===")
        print(f"  {len(diffs)} value registers differ, "
              f"{len(addrs)} address registers differ, "
              f"{len(onlya)} only in rgu, {len(onlyb)} only in dwu")
        for k in onlya:
            print(f"    only rgu  {TARGETS[k[0]]:5s} 0x{k[1]:04x} = "
                  f"{[f'0x{v:08x}' for v in ma[k]]}")
        for k in onlyb:
            print(f"    only dwu  {TARGETS[k[0]]:5s} 0x{k[1]:04x} = "
                  f"{[f'0x{v:08x}' for v in mb[k]]}")
        for k in diffs:
            va = [f"0x{v:08x}" for v in ma[k]]
            vb = [f"0x{v:08x}" for v in mb[k]]
            print(f"    {TARGETS[k[0]]:5s} 0x{k[1]:04x}  rgu {','.join(va)}"
                  f"   dwu {','.join(vb)}")
        if i == 0 and addrs:
            print("    (address registers, listed but not counted: "
                  + ", ".join(f"{TARGETS[k[0]]}:0x{k[1]:04x}" for k in addrs)
                  + ")")


if __name__ == "__main__":
    main()
