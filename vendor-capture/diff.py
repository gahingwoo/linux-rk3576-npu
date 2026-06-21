#!/usr/bin/env python3
"""
Extract the CNA (and optionally other unit) register map from each .rknn and
tabulate reg -> value across tags so registers that change with a swept conv
parameter are obvious.

Usage: diff.py [--unit CNA] tag1 tag2 [tag3 ...]
  tags resolve to work/<tag>.rknn
Prints a table: reg | tag1 | tag2 | ...  with a '*' marker on rows that differ.
"""
import sys, struct

TARGETS = {0x0201: "CNA", 0x0801: "CORE", 0x1001: "DPU",
           0x2001: "RDMA", 0x0041: "SYNC", 0x0081: "BCAST"}
NAME2TGT = {v: k for k, v in TARGETS.items()}

def regmap(path, want_tgt):
    data = open(path, "rb").read()
    n = len(data) // 8
    words = struct.unpack("<%dQ" % n, data[:n*8])
    # find longest run of valid-target u64s (the regcmd stream)
    best = (0, 0)
    i = 0
    while i < n:
        if ((words[i] >> 48) & 0xffff) in TARGETS:
            j = i
            while j < n and ((words[j] >> 48) & 0xffff) in TARGETS:
                j += 1
            if j - i > best[1]:
                best = (i, j - i)
            i = j
        else:
            i += 1
    start, length = best
    m = {}
    order = []
    for k in range(start, start + length):
        e = words[k]
        tgt = (e >> 48) & 0xffff
        if tgt != want_tgt:
            continue
        val = (e >> 16) & 0xffffffff
        reg = e & 0xffff
        if reg not in m:
            order.append(reg)
        m[reg] = val          # last write wins (matches HW)
    return m, order

def main():
    args = sys.argv[1:]
    unit = "CNA"
    if args and args[0] == "--unit":
        unit = args[1]; args = args[2:]
    tags = args
    want = NAME2TGT[unit]
    maps = []
    allregs = []
    seen = set()
    for t in tags:
        m, order = regmap(f"work/{t}.rknn", want)
        maps.append(m)
        for r in order:
            if r not in seen:
                seen.add(r); allregs.append(r)

    hdr = "reg     " + "".join("%-12s" % t for t in tags)
    print("[unit %s]" % unit)
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(allregs):
        vals = [m.get(r) for m in maps]
        cells = "".join(("%08x" % v if v is not None else "--------").ljust(12) for v in vals)
        diff = len(set(v for v in vals if v is not None)) > 1 or any(v is None for v in vals)
        print("%04x  %s %s" % (r, "*" if diff else " ", cells))

if __name__ == "__main__":
    main()
