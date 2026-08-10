#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Resolve the vendor's address registers into the captured buffers.

The weight buffer and the register values are both now accounted for on the
depthwise side: mesa's 576 byte depthwise packing reproduces the vendor's
weight lanes 288 out of 288, and all fourteen registers that move between
sv_rgu and sv_dwu already carry the vendor's own values in rkt_regcmd.c. What
is left is where the depthwise layer's per-channel data comes from, given that
the vendor emits no A/B/C table for it and switches BRDMA to 0x0510.

Every address register in the stream is a device address, and meta.txt gives
the dma address and size of each captured buffer, so each one can be turned
into a buffer and an offset and the bytes there can be looked at. That replaces
guessing about which buffer is which.

The float32 bias array is known here exactly, so it is searched for in every
buffer as well: if the depthwise bias is in memory at all, this finds it and
says whether any address register points near it.
"""
import os
import re
import struct
import sys

import numpy as np

from extract_regcmd import TARGETS, decode

ADDR_REGS = [0x100c, 0x1088, 0x1110, 0x4018, 0x5020, 0x5024, 0x5004, 0x3004,
             0x1004, 0x4004, 0x2004, 0x2008, 0x2014, 0x2018]


def bos(path):
    out = []
    for ln in open(os.path.join(path, "meta.txt")):
        m = re.match(r"bo idx=(\d+) handle=\d+ dma=0x([0-9a-f]+) \S+ size=(\d+)", ln)
        if m:
            out.append((int(m.group(1)), int(m.group(2), 16), int(m.group(3))))
    return out


def first_run(path):
    d = open(os.path.join(path, "bo01.bin"), "rb").read()
    n = len(d) // 8
    w = struct.unpack("<%dQ" % n, d[:n * 8])
    i = 0
    while i < n:
        if ((w[i] >> 48) & 0xffff) in TARGETS:
            j = i
            while j < n and ((w[j] >> 48) & 0xffff) in TARGETS:
                j += 1
            if j - i >= 40:
                return [decode(w[k]) for k in range(i, j)]
            i = j
        else:
            i += 1
    return []


def resolve(addr, bl):
    for idx, dma, size in bl:
        if dma <= addr < dma + size:
            return idx, addr - dma
    return None, None


def known_bias():
    rng = np.random.RandomState(7)
    return (rng.randn(32) * 0.05).astype(np.float32)


def report(root, tag):
    path = os.path.join(root, tag)
    bl = bos(path)
    entries = first_run(path)
    print(f"\n=== {tag} ===")
    for idx, dma, size in bl:
        print(f"  bo{idx}: dma 0x{dma:08x} size {size}")
    seen = set()
    for tgt, val, reg in entries:
        if reg not in ADDR_REGS or (tgt, reg) in seen:
            continue
        seen.add((tgt, reg))
        idx, off = resolve(val, bl)
        where = f"bo{idx}+0x{off:05x}" if idx is not None else "not in any bo"
        head = ""
        if idx is not None:
            raw = open(os.path.join(path, f"bo{idx:02d}.bin"), "rb").read()
            head = " ".join(f"{b:02x}" for b in raw[off:off + 16])
        print(f"  {TARGETS[tgt]:5s} 0x{reg:04x} = 0x{val:08x}  {where}  {head}")

    bias = known_bias()
    nb = bias.tobytes()
    for idx, dma, size in bl:
        raw = open(os.path.join(path, f"bo{idx:02d}.bin"), "rb").read()
        i = raw.find(nb)
        if i >= 0:
            print(f"  float32 bias array found verbatim at bo{idx}+0x{i:05x} "
                  f"(dma 0x{dma + i:08x})")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "../dirty/vendorcap-dw-2026-08-10"
    report(root, "sv_rgu")
    report(root, "sv_dwu")
