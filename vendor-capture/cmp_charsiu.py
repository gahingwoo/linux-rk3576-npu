#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Diff charsiu's COMPLETE job stream against a vendor int8 convolution compiled at
the same shape, with no activation.

The existing charsiu tools/cmp_vendor.py compares the geometry emitter only, 29
registers of the 143 the job actually submits, which is why a full stream had
never been checked against the vendor's. This runs charsiu's build/emit_job and
compares every entry.

The reference is geom/a_lin_m1_rk3576.rknn from gen_act.py: 64 to 64, one row,
one pixel, int8 weights, no ReLU. That is charsiu's own shape, compiled by the
vendor's compiler, so a difference is charsiu's and not the shape's.

Usage: cmp_charsiu.py [M K N] [model.rknn]
"""
import os
import subprocess
import sys

sys.path.insert(0, "/home/parallels/Desktop/charsiu/tools")
from rkllm_regcmd import streams, decode, geometry     # noqa: E402

TAG = {0x201: "CNA", 0x801: "CORE", 0x1001: "DPU", 0x2001: "RDMA",
       0x41: "SYNC", 0x81: "BCAST"}
EMIT = "/home/parallels/Desktop/charsiu/build/emit_job"

# Registers whose value is the model's own quantisation or an address, so a
# difference there is expected and says nothing. Everything else is real.
QUANT = {(0x1001, 0x40ac), (0x1001, 0x40b0), (0x1001, 0x40b4),
         (0x201, 0x1084)}
ADDR = {(0x201, 0x1088), (0x201, 0x1110), (0x1001, 0x4018),
        (0x201, 0x1100), (0x201, 0x1104),
        (0x2001, 0x5020), (0x2001, 0x5024)}   # the coefficient buffer

# The four op enables. A static model file does not carry them, because the
# vendor runtime appends them when it submits; their absence is not a
# difference. Round 141 lost a board round to a stream that had no enables.
ENABLE = {(0x201, 0x1008), (0x801, 0x3008), (0x1001, 0x4008), (0x2001, 0x5008)}


def main():
    m, k, n = 1, 64, 64
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "geom/a_lin_m1_rk3576.rknn")
    args = sys.argv[1:]
    if len(args) >= 3:
        m, k, n = int(args[0]), int(args[1]), int(args[2])
        args = args[3:]
    if args:
        path = args[0]

    ours = {}
    out = subprocess.run([EMIT, str(m), str(k), str(n)],
                         capture_output=True, text=True)
    if out.returncode:
        print("emit_job failed: %s" % out.stderr.strip())
        return 1
    # the printf is "CS %02d t=%04x r=%04x v=%08x"
    for line in out.stdout.split("\n"):
        if not line.startswith("CS "):
            continue
        parts = line.split()
        t = int(parts[2].split("=")[1], 16)
        r = int(parts[3].split("=")[1], 16)
        v = int(parts[4].split("=")[1], 16)
        ours.setdefault((t, r), v)

    vend = None
    for off, ws in streams(path):
        regs = decode(ws)
        g = geometry(regs)
        if g and g["ic"] == k and g["oc"] == n and g["rows"] == m:
            vend = regs
            break
    if vend is None:
        print("no vendor stream at M=%d K=%d N=%d in %s" % (m, k, n, path))
        return 1

    print("charsiu %d entries, vendor %d, M=%d K=%d N=%d\n"
          % (len(ours), len(vend), m, k, n))
    print("  %-5s %-6s %-10s %-10s" % ("", "reg", "charsiu", "vendor"))
    real = 0
    for key in sorted(set(ours) | set(vend), key=lambda x: (x[0], x[1])):
        a, b = ours.get(key), vend.get(key)
        if a == b:
            continue
        why = ""
        if key in QUANT:
            why = "  (this model's quantisation)"
        elif key in ADDR:
            why = "  (address, 0 in a static file)"
        elif key in ENABLE:
            why = "  (op enable, appended at submit)"
        else:
            real += 1
        print("  %-5s %04x   %-10s %-10s%s"
              % (TAG.get(key[0], "?"), key[1],
                 "--" if a is None else "%08x" % a,
                 "--" if b is None else "%08x" % b, why))
    print("\n  %d differences that are not an address, this model's\n  quantisation, or an op enable" % real)
    return 0


if __name__ == "__main__":
    sys.exit(main())
