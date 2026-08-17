#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Find the coefficient record table inside the captured buffers, on the board.

The first two capture passes dumped offset zero of every buffer and none of them
opened with the records: bo00 is a descriptor list, bo01 is weights, bo03 is the
ramp input and bo02 and bo04 start zeroed. The records are in the .rknn at
0x8540, so at runtime they sit at some offset inside one of these rather than at
the front of one, and guessing that offset from here is what this script is for
instead.

Two ways of looking, because either can fail on its own. The KEY is the exact
first sixteen bytes of the table as it appears in the model file, which finds it
if the runtime copies it verbatim. The STRUCTURE test finds it even if the
runtime rebuilds it: eight int32 addends, then eight int16, then eight int16
that sit between 8000 and 16384, which is what a Q14 per channel scale looks
like and what nothing else in these buffers looks like.

Usage: find_coef.py <key-hex> <file> [file ...]
"""
import struct
import sys


def structural(raw, off):
    if off + 64 > len(raw):
        return False
    A = struct.unpack_from("<8i", raw, off)
    B = struct.unpack_from("<8h", raw, off + 32)
    C = struct.unpack_from("<8h", raw, off + 48)
    return (any(abs(a) > 1000 for a in A) and all(abs(a) < 5_000_000 for a in A)
            and all(-3000 < b < 3000 for b in B)
            and all(8000 < c <= 16384 for c in C))


def main():
    key = bytes.fromhex(sys.argv[1])
    for path in sys.argv[2:]:
        raw = open(path, "rb").read()
        name = path.split("/")[-1]

        at = raw.find(key)
        print(f"  {name} size={len(raw)}  key at "
              f"{('0x%x' % at) if at >= 0 else 'not found'}")

        hits = [o for o in range(0, len(raw) - 64, 64) if structural(raw, o)]
        if hits:
            runs = []
            for o in hits:
                if runs and o == runs[-1][1] + 64:
                    runs[-1][1] = o
                else:
                    runs.append([o, o])
            for a, b in runs[:4]:
                print(f"    structural match 0x{a:x} to 0x{b:x}"
                      f"  ({(b - a) // 64 + 1} records)")
        else:
            print("    no structural match")

        show = at if at >= 0 else (hits[0] if hits else -1)
        if show >= 0:
            print(f"    1280 bytes from 0x{show:x}:")
            for i in range(0, min(1280, len(raw) - show), 64):
                print("      " + raw[show + i:show + i + 64].hex())


main()
