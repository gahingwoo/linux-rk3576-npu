#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
List the byte vectors inside a .rknn file, and diff two of them.

Why this exists: the coefficient buffer the vendor driver hands the hardware is
not synthesised at load time, it is *stored in the .rknn*. Mapping the 8192 byte
buffer captured from the board back into `g_cal_rk3576.rknn` places every
model-dependent part of it in four contiguous chunks:

    coef 0x000..0x400  the A/B/C table       rknn 0x8540  1024 bytes
    coef 0x400..0x500  128 uint16, per oc    rknn 0x37c0   256 bytes
    coef 0x500..0x700                        rknn 0x81c0   512 bytes
    coef 0x700..0xb00                        rknn 0x7d80  1024 bytes

and all four sit behind an exact uint32 length prefix, which is how flatbuffers
stores a `[ubyte]`. Everything past coef 0x0b90 is the model-independent
constant already saved as vendor-coef-tail-0x0b90.bin.

So the open question, what the vendor writes in coef `0x400..0x0b90`, is an
OFFLINE question now. Compile a model on the host, pull the vectors out, and
compare. No board, no SPI reflash, no capture image.

The scan is a heuristic over a container this project has not parsed, so it is
checked against those four known chunks on every run of the self test.

Usage: rknn_blobs.py list <a.rknn>
       rknn_blobs.py diff <a.rknn> <b.rknn>
       rknn_blobs.py selftest
"""
import hashlib
import os
import struct
import sys

SCR = os.path.dirname(os.path.abspath(__file__))


def vectors(path, min_len=64, max_len=1 << 20):
    """Every plausible flatbuffer [ubyte] vector, largest first per offset.

    A vector is a uint32 length followed by that many bytes. Requiring the
    length to be a multiple of 16 and the four bytes before it to be zero
    padding cuts the candidates from hundreds to a handful without needing the
    schema; the self test is what says the filter did not drop a real one.

    ⚠ This was 64 first, which silently dropped every table whose size is not
    64 aligned: with oc=48 the per-channel table is 96 bytes and vanished, and
    the locator reported "not found" rather than "filtered out".
    """
    d = open(path, "rb").read()
    out = []
    for o in range(4, len(d) - 8, 4):
        L = struct.unpack_from("<I", d, o)[0]
        if not (min_len <= L <= max_len) or o + 4 + L > len(d):
            continue
        if L % 16:
            continue
        if struct.unpack_from("<I", d, o - 4)[0] != 0:
            continue
        out.append((o + 4, L, d[o + 4:o + 4 + L]))
    return d, out


def show(path):
    d, vs = vectors(path)
    print(f"{os.path.basename(path)}  {len(d)} bytes, {len(vs)} vectors")
    for off, L, b in vs:
        nz = sum(1 for x in b if x)
        print(f"  0x{off:06x}  {L:7d}  nonzero {nz:6d}  "
              f"{hashlib.sha1(b).hexdigest()[:12]}")


def diff(a, b):
    _, va = vectors(a)
    _, vb = vectors(b)
    ha = {hashlib.sha1(x[2]).hexdigest(): x for x in va}
    hb = {hashlib.sha1(x[2]).hexdigest(): x for x in vb}
    same = set(ha) & set(hb)
    print(f"{os.path.basename(a)}: {len(va)} vectors   "
          f"{os.path.basename(b)}: {len(vb)} vectors   identical: {len(same)}")

    # Pair up what differs by length, which is what a single-variable pair
    # should leave: same sizes, different contents.
    onlya = sorted((v for h, v in ha.items() if h not in same), key=lambda v: v[0])
    onlyb = sorted((v for h, v in hb.items() if h not in same), key=lambda v: v[0])
    bylen = {}
    for v in onlya:
        bylen.setdefault(v[1], [[], []])[0].append(v)
    for v in onlyb:
        bylen.setdefault(v[1], [[], []])[1].append(v)

    for L in sorted(bylen):
        xs, ys = bylen[L]
        print(f"\n  size {L}: {len(xs)} in A, {len(ys)} in B")
        for x, y in zip(xs, ys):
            n = sum(1 for i in range(L) if x[2][i] != y[2][i])
            print(f"    A 0x{x[0]:06x} vs B 0x{y[0]:06x}: "
                  f"{n}/{L} bytes differ ({100.0*n/L:.1f}%)")
            if n and n < L:
                idx = [i for i in range(L) if x[2][i] != y[2][i]]
                runs, s = [], idx[0]
                for i in range(1, len(idx)):
                    if idx[i] != idx[i-1] + 1:
                        runs.append((s, idx[i-1])); s = idx[i]
                runs.append((s, idx[-1]))
                head = ", ".join(f"0x{a:x}..0x{b:x}" for a, b in runs[:8])
                print(f"      differing runs: {head}"
                      f"{' ...' if len(runs) > 8 else ''}  ({len(runs)} runs)")
        for x in xs[len(ys):]:
            print(f"    A only 0x{x[0]:06x}")
        for y in ys[len(xs):]:
            print(f"    B only 0x{y[0]:06x}")


def selftest():
    """The filter must still find the four chunks the board capture landed in."""
    rk = f"{SCR}/geom/g_cal_rk3576.rknn"
    buf = open(f"{SCR}/vendor-coefbuf-k5.bin", "rb").read()
    _, vs = vectors(rk)
    found = {off: L for off, L, _ in vs}
    ok = True
    for off, L, coef in ((0x8540, 1024, 0x000), (0x37c0, 256, 0x400),
                         (0x81c0, 512, 0x500), (0x7d80, 1024, 0x700)):
        hit = found.get(off) == L
        blob = [v[2] for v in vs if v[0] == off]
        match = bool(blob) and blob[0] == buf[coef:coef + L]
        print(f"  rknn 0x{off:04x} len {L:5d} -> coef 0x{coef:04x}: "
              f"vector {'found' if hit else 'MISSING'}, "
              f"content {'matches capture' if match else 'DIFFERS'}")
        ok &= hit and match
    print(f"  {len(vs)} vectors survive the filter")
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def chunks(path, oc):
    """The two chunks that survive a recompile, located by size.

    Read off the oc ladder g_oc32 to g_oc160, both rules hold across all nine:

      A/B/C     8 bytes per output channel, PADDED UP to a multiple of 32
                channels, and it is the last vector of that size in the file.
      per-oc    2 bytes per output channel, unpadded, and the first of its size.

    Returns (abc, per_oc), each (offset, length, bytes) or None.

    Everything between them in the buffer, coef 0x500 to 0x0b90, is skipped on
    purpose: four compiles of one identical model showed it is not reproducible,
    so there is nothing there to compare.
    """
    _, vs = vectors(path, min_len=32)
    pad = ((oc + 31) // 32) * 32
    abc = [v for v in vs if v[1] == 8 * pad]
    per = [v for v in vs if v[1] == 2 * oc] or [v for v in vs if v[1] == 2 * pad]
    return (abc[-1] if abc else None), (per[0] if per else None)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "list":
        show(sys.argv[2])
    elif cmd == "diff":
        diff(sys.argv[2], sys.argv[3])
    else:
        sys.exit(selftest())
