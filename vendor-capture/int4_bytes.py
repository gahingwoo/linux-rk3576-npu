#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
How does the vendor count int4 weight bytes, and does the ACTIVATION precision
change it?

Round 171 read the weight buffer with one live nibble at a time and found the
hardware fetching only the first 1024 bytes of a 2048 byte buffer for a 64 by 64
int4 matmul, with 8 bytes per output channel per group rather than the 32 a
channel needs. Half the weights are not being read at all. That is a byte
accounting question and not a layout one, so it belongs here rather than on the
board.

charsiu's constants for int4 were confirmed against ONE vendor stream, at
ic = 2048 with 16 bit activations. Two things were never checked: whether they
are a formula in k and n rather than the values at that one point, and whether
they move with the activation precision the way surf does. The file has int4
streams both with and without bit 29 of 0x100c set, so the second question can be
answered by looking for a shape that appears in both groups.

Usage: int4_bytes.py [model.rkllm]
"""
import sys
from collections import defaultdict

sys.path.insert(0, "/home/parallels/Desktop/charsiu/tools")
from rkllm_regcmd import streams, decode, geometry     # noqa: E402

REGS = [0x101c, 0x1020, 0x1024, 0x1028, 0x1030, 0x107c, 0x100c, 0x1044]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/parallels/Documents/kiln/model/Llama-3.2-1B-Instruct-rk3576-w4a16.rkllm"

    rows = {}
    for off, ws in streams(path):
        regs = decode(ws)
        g = geometry(regs)
        if not g:
            continue
        cfg = regs.get((0x201, 0x100c), 0)
        key = (g["weight_bits"], g["ic"], g["oc"], bool(cfg & 0x20000000))
        rows.setdefault(key, regs)

    print("%s\n" % path)
    print("  %-5s %-6s %-6s %-4s | %-9s %-8s %-9s %-9s %-8s"
          % ("wbit", "ic", "oc", "a16", "101c", "1020", "1030", "107c", "1024"))
    for key in sorted(rows):
        wb, ic, oc, a16 = key
        r = rows[key]
        g = lambda x: r.get((0x201, x), 0)
        print("  %-5s %-6d %-6d %-4s | %-9d %-8d %-9d %-9d %-8d"
              % (wb, ic, oc, "yes" if a16 else "no",
                 g(0x101c), g(0x1020), g(0x1030) >> 16, g(0x107c), g(0x1024)))

    print("\n  against the formulas charsiu uses:")
    print("  %-5s %-6s %-6s %-4s | %-22s %-18s %-18s"
          % ("wbit", "ic", "oc", "a16", "101c vs k*n/bpw", "1020 vs k/bpw",
             "1030hi vs k/bpw"))
    for key in sorted(rows):
        wb, ic, oc, a16 = key
        r = rows[key]
        g = lambda x: r.get((0x201, x), 0)
        bpw = {4.0: 2.0, 8.0: 1.0, 16.0: 0.5}.get(wb)
        if not bpw:
            continue
        want_c = ic * oc / bpw
        want_20 = ic / bpw
        want_30 = ic / bpw
        print("  %-5s %-6d %-6d %-4s | %-9d %-11s %-8d %-9s %-8d %-9s"
              % (wb, ic, oc, "yes" if a16 else "no",
                 g(0x101c), "ok" if g(0x101c) == want_c else "want %d" % want_c,
                 g(0x1020), "ok" if g(0x1020) == want_20 else "want %d" % want_20,
                 g(0x1030) >> 16,
                 "ok" if (g(0x1030) >> 16) == want_30 else "want %d" % want_30))

    # Does the ACTIVATION precision move the weight byte registers? Look for a
    # shape present in both the a16 and the a8 int4 groups.
    both = defaultdict(dict)
    for (wb, ic, oc, a16), r in rows.items():
        if wb == 4.0:
            both[(ic, oc)][a16] = r
    print("\n  int4 shapes present at BOTH activation precisions:")
    found = False
    for (ic, oc), d in sorted(both.items()):
        if len(d) < 2:
            continue
        found = True
        print("    ic=%d oc=%d" % (ic, oc))
        for reg in REGS:
            a = d[False].get((0x201, reg))
            b = d[True].get((0x201, reg))
            mark = "" if a == b else "   <-- MOVES WITH THE ACTIVATION"
            print("      %04x  a8 %-10s a16 %-10s%s"
                  % (reg,
                     "--" if a is None else "%08x" % a,
                     "--" if b is None else "%08x" % b, mark))
    if not found:
        print("    none, so the file cannot answer that question by itself")
    return 0


if __name__ == "__main__":
    sys.exit(main())
