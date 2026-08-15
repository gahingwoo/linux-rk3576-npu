#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
What does the vendor change to run a matmul in int4 rather than int8?

Read straight out of the .rkllm, on a desktop. The file carries 3328 streams with
four bit weights and 40 with eight bit ones, so the two precisions can be diffed
against each other at the same geometry with nothing but arithmetic.

This has to be answered before any int4 board round. charsiu's int4 numbers
today are a group of 64 copied from the RK3588 notes and a 0x100c constant lifted
from a vendor fp16 stream, neither confirmed here, and its packer returns early
rather than pretend. A board round that guesses the registers cannot read a
layout, because a wrong register and a wrong layout produce the same wrong bytes.

Usage: int4_regs.py [model.rkllm]
"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/home/parallels/Desktop/charsiu/tools")
from rkllm_regcmd import streams, decode, geometry     # noqa: E402

TAG = {0x201: "CNA", 0x801: "CORE", 0x1001: "DPU", 0x2001: "RDMA"}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/parallels/Documents/kiln/model/Llama-3.2-1B-Instruct-rk3576-w4a16.rkllm"

    by_bits = defaultdict(list)
    for off, ws in streams(path):
        regs = decode(ws)
        g = geometry(regs)
        if g:
            by_bits[g["weight_bits"]].append((off, g, regs))

    print("%s\n" % path)
    for b in sorted(by_bits):
        shapes = Counter((g["ic"], g["oc"], g["rows"]) for _, g, _ in by_bits[b])
        print("  %-6s bits: %5d streams, %3d shapes, commonest %s"
              % (b, len(by_bits[b]), len(shapes), shapes.most_common(2)))

    # The weight byte register is the first thing to check: it says how the
    # hardware is being told to count a nibble.
    print("\n0x101c against ic * oc, which is what says how a nibble is counted:")
    print("  %-6s %-7s %-7s %-12s %-8s" % ("bits", "ic", "oc", "0x101c", "ratio"))
    seen = set()
    for b in sorted(by_bits):
        for off, g, regs in by_bits[b]:
            key = (b, g["ic"], g["oc"])
            if key in seen:
                continue
            seen.add(key)
            wt = regs.get((0x201, 0x101c), 0)
            print("  %-6s %-7d %-7d %-12d %-8.3f"
                  % (b, g["ic"], g["oc"], wt, wt / (g["ic"] * g["oc"])))
            if len(seen) > 14:
                break
        if len(seen) > 14:
            break

    # And the register level diff: pick an int4 stream and an int8 one and show
    # every register that differs, so the precision switch is a list and not a
    # guess.
    if 4.0 in by_bits and 8.0 in by_bits:
        _, g4, r4 = by_bits[4.0][0]
        _, g8, r8 = by_bits[8.0][0]
        print("\nint4 %s  against  int8 %s"
              % ((g4["ic"], g4["oc"], g4["rows"]), (g8["ic"], g8["oc"], g8["rows"])))
        print("  (shapes differ, so geometry registers differ for that reason;\n"
              "   what matters is a register that differs and is NOT geometry)\n")
        print("  %-5s %-6s %-10s %-10s" % ("", "reg", "int4", "int8"))
        for k in sorted(set(r4) | set(r8), key=lambda x: (x[0], x[1])):
            a, b_ = r4.get(k), r8.get(k)
            if a == b_:
                continue
            print("  %-5s %04x   %-10s %-10s"
                  % (TAG.get(k[0], "?"), k[1],
                     "--" if a is None else "%08x" % a,
                     "--" if b_ is None else "%08x" % b_))

    # 0x100c is the register charsiu currently guesses for int4. What do the
    # int4 streams actually carry, and is it one value or several?
    print("\nCNA 0x100c across the whole file, by weight precision:")
    for b in sorted(by_bits):
        vals = Counter(regs.get((0x201, 0x100c)) for _, _, regs in by_bits[b])
        print("  %-6s bits: %s"
              % (b, {("%08x" % v if v is not None else None): c
                     for v, c in vals.most_common(4)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
