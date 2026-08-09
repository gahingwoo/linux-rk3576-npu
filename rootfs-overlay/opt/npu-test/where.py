#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Where in a buffer are the written bytes?

The depthwise output BO holds 256 written bytes out of 51200. Whether those sit
in one run at the start, or are strided across the surface, says different
things: a single leading run means the write stopped after one atom, while a
stride means it wrote one slice of every position and skipped the rest.

Prints the nonzero extent, the run structure, and the stride between runs.

Usage: where.py <file.bin> [expected_atom_bytes]
"""
import sys

data = open(sys.argv[1], "rb").read()
atom = int(sys.argv[2]) if len(sys.argv) > 2 else 256

nz = [i for i, b in enumerate(data) if b != 0]
print(f"  {sys.argv[1].split('/')[-1]}: {len(data)} bytes, {len(nz)} nonzero "
      f"({100.0 * len(nz) / len(data):.2f}%)", flush=True)
if not nz:
    print("    all zero", flush=True)
    sys.exit(0)

print(f"    first nonzero at {nz[0]}, last at {nz[-1]}", flush=True)

# contiguous runs of nonzero
runs = []
start = prev = nz[0]
for i in nz[1:]:
    if i != prev + 1:
        runs.append((start, prev - start + 1))
        start = i
    prev = i
runs.append((start, prev - start + 1))

print(f"    {len(runs)} contiguous run(s)", flush=True)
for off, ln in runs[:8]:
    print(f"      offset {off:7d}  length {ln}", flush=True)
if len(runs) > 8:
    print(f"      ... and {len(runs) - 8} more", flush=True)

if len(runs) > 1:
    strides = {runs[i + 1][0] - runs[i][0] for i in range(min(len(runs), 12) - 1)}
    print(f"    stride between run starts: {sorted(strides)}", flush=True)

print(f"    (one atom = {atom} bytes; written = {len(nz)} = {len(nz) / atom:.2f} atoms)",
      flush=True)
