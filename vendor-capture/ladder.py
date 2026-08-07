#!/usr/bin/env python3
"""
What does the VENDOR put in the CNA registers mesa fills from a hardcoded ladder?

Round 3's regcmd diff (conv2d-cal, which computes, against cal_s1, the same model
with only the stride changed, which does not) came out at 14 differing entries.
Ten are plain geometry. Four are not: 0x1014, 0x1018, 0x1040 and 0x1080, and in
rkt_regcmd.c all four are `s == 2 ? <constant> : <other constant>` ladders fitted
to the handful of vendor captures this project has. 0x1080 is CNA_DMA_CON2, whose
only field is a 28-bit SURF_STRIDE, and mesa emits a captured 0x02020101 for a
stride-2 conv and plain 0 for a stride-1 one.

That would explain the whole table: exactly one geometry computes because exactly
one branch was fitted against a vendor capture of that geometry.

This reads those registers back out of vendor .rknn files, which the toolkit
compiles on the host, so the ladder can be checked against real values at
geometries nobody captured.

⚠ Address registers in a static .rknn are unpatched placeholders and read 0.
None of the four are addresses.

Usage: ladder.py <file.rknn> [more.rknn ...]
"""
import struct
import sys

TARGETS = {0x0201: "CNA", 0x0801: "CORE", 0x1001: "DPU", 0x2001: "RDMA",
           0x0041: "SYNC", 0x0081: "BCAST"}
WATCH = [0x1014, 0x1018, 0x1024, 0x1028, 0x102c, 0x1030, 0x1034, 0x1040,
         0x1044, 0x1078, 0x107c, 0x1080, 0x1090, 0x1094, 0x1098]


def streams(path):
    """Every maximal run of valid regcmd entries in the file."""
    data = open(path, "rb").read()
    n = len(data) // 8
    words = struct.unpack("<%dQ" % n, data[:n * 8])
    out, i = [], 0
    while i < n:
        if ((words[i] >> 48) & 0xffff) in TARGETS:
            j = i
            while j < n and ((words[j] >> 48) & 0xffff) in TARGETS:
                j += 1
            if j - i >= 40:
                out.append([((w >> 48) & 0xffff, (w >> 16) & 0xffffffff, w & 0xffff)
                            for w in words[i:j]])
            i = j
        else:
            i += 1
    return out


def main():
    for path in sys.argv[1:]:
        for k, s in enumerate(streams(path)):
            vals = {}
            for tgt, val, reg in s:
                if tgt == 0x0201 and reg in WATCH and reg not in vals:
                    vals[reg] = val
            if not vals:
                continue
            print(f"{path} stream{k} ({len(s)} entries)")
            print("   " + "  ".join(f"{r:04x}={vals[r]:08x}"
                                    for r in WATCH if r in vals))


main()
