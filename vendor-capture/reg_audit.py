#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Audit the register CONSTANTS mesa hardcodes against a vendor .rknn compiled at
the same geometry, without a board.

Round 29 left a puzzle: the vendor's model files hold one fp16 per output
channel at coef 0x400, mesa holds float32 dequantised weights across
0x400..0x0b90, every byte of mesa's version is load bearing, and both compute.
The same bytes cannot be read two ways on their own, so something outside the
buffer differs. The DPU_RDMA block is the natural suspect because 0x5024 points
a second SDP operand at exactly that address.

mesa writes most of that block as literals, so they can be compared with what
the vendor actually emits at a matching geometry, straight out of the .rknn. No
runtime, no hardware. Values that mesa computes from the geometry are reported
separately rather than silently skipped, because "not compared" and "compared
and equal" are different answers.

⚠ Base addresses in a .rknn are relocation placeholders, usually zero. They are
listed but never counted as a mismatch.

Usage: reg_audit.py [vendor.rknn] [regcmd source]
"""
import os
import re
import sys

SCR = os.path.dirname(os.path.abspath(__file__))
RKNN = sys.argv[1] if len(sys.argv) > 1 else f"{SCR}/geom/g_cal_rk3576.rknn"
SRC = (sys.argv[2] if len(sys.argv) > 2 else
       f"{SCR}/../mesa/mesa-src/src/gallium/drivers/rocket/rkt_regcmd.c")

ADDR_REGS = {0x1088, 0x1110, 0x4018, 0x5020, 0x5024, 0x5004, 0x3004, 0x1004,
             0x4004}

sys.path.insert(0, SCR)
from extract_regcmd import decode, TARGETS  # noqa: E402
import struct  # noqa: E402


def vendor_regs(path):
    """The longest valid run of regcmd u64s, as {reg: value}, first write wins."""
    d = open(path, "rb").read()
    best, cur, start = (0, 0), 0, 0
    for i in range(0, len(d) - 8, 8):
        e = struct.unpack_from("<Q", d, i)[0]
        if ((e >> 48) & 0xffff) in TARGETS:
            if cur == 0:
                start = i
            cur += 1
            if cur > best[0]:
                best = (cur, start)
        else:
            cur = 0
    n, off = best
    regs = {}
    for i in range(off, off + n * 8, 8):
        e = struct.unpack_from("<Q", d, i)[0]
        reg = e & 0xffff
        val = (e >> 16) & 0xffffffff
        regs.setdefault(reg, val)
    return regs, n


def mesa_literals(path):
    """Every R_CNA/R_CORE/R_DPU/R_RDMA(reg, <literal>) in the file."""
    s = open(path).read()
    out, computed = {}, {}
    pat = re.compile(r"R_(CNA|CORE|DPU|RDMA)\(\s*(0x[0-9a-fA-F]+)\s*,\s*([^;]+?)\);")
    for m in pat.finditer(s):
        reg = int(m.group(2), 16)
        expr = m.group(3).strip()
        lit = re.fullmatch(r"0x[0-9a-fA-F]+|\d+", expr)
        if lit:
            out.setdefault(reg, int(expr, 0))
        else:
            computed.setdefault(reg, expr)
    return out, computed


if __name__ == "__main__":
    regs, n = vendor_regs(RKNN)
    lits, comp = mesa_literals(SRC)

    print(f"vendor {os.path.basename(RKNN)}: {n} regcmd entries, {len(regs)} distinct regs")
    print(f"mesa   {os.path.basename(SRC)}: {len(lits)} literal regs, "
          f"{len(comp)} computed\n")

    same = diff = 0
    mismatches = []
    for reg in sorted(lits):
        if reg not in regs:
            continue
        if reg in ADDR_REGS:
            continue
        if lits[reg] == regs[reg]:
            same += 1
        else:
            diff += 1
            mismatches.append((reg, lits[reg], regs[reg]))

    print(f"literal regs present in both: {same + diff}   equal: {same}   "
          f"DIFFERENT: {diff}")
    if mismatches:
        print("\n  reg     mesa        vendor")
        for reg, m, v in mismatches:
            print(f"  0x{reg:04x}  0x{m:08x}  0x{v:08x}")

    only = [r for r in sorted(lits) if r not in regs and r not in ADDR_REGS]
    if only:
        print(f"\nmesa writes but this vendor model does not ({len(only)}): "
              + " ".join(f"0x{r:04x}" for r in only[:24])
              + (" ..." if len(only) > 24 else ""))
    vonly = [r for r in sorted(regs) if r not in lits and r not in comp
             and r not in ADDR_REGS]
    if vonly:
        print(f"\nvendor writes but mesa has no literal for ({len(vonly)}): "
              + " ".join(f"0x{r:04x}" for r in vonly[:24])
              + (" ..." if len(vonly) > 24 else ""))

    print("\ncomputed by mesa, so NOT compared here (vendor value shown for "
          "hand checking):")
    for reg in sorted(comp):
        if reg in regs and reg not in ADDR_REGS:
            e = comp[reg] if len(comp[reg]) < 44 else comp[reg][:41] + "..."
            print(f"  0x{reg:04x}  vendor 0x{regs[reg]:08x}   mesa: {e}")
