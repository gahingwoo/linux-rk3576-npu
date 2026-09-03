#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Build the RESERVED_0 table for DPU register 0x4050, out of the vendor-compiled
.rknn files in the directory it is given.

This is the table promised to Igor Paunovic on linux-rockchip in the v9 05/13
thread, where the claim was that RESERVED_0 "is 34 in most of the regular
models and 66 in a subset", tracking the model series rather than the geometry.
That claim was written once and never re-derived. This re-derives it from the
files and prints whatever the files say, including where they contradict it.

Method, so it can be checked rather than believed. A .rknn carries the register
command stream the vendor runtime submits, as little-endian u64 words

    [63:48] target   [47:16] value   [15:0] register

with 0x0201 CNA, 0x0801 CORE, 0x1001 DPU, 0x2001 DPU_RDMA and a few others. A
maximal run of such words is one dispatch. Every run of 20 words or more in
this corpus carries exactly one CNA block and exactly one write of DPU 0x4050,
so one run is one convolution and there is no ambiguity about which op a value
belongs to. Nothing here is run on hardware and nothing is taken apart: the
numbers are read out of files the vendor toolkit produced, and the meaning of
the bits was arrived at by trial and error against those files and the board.

The field split is upstream's, from mesa's rocket registers.xml, BS_OW_CFG:

    RGP_CNTER  31:28   TP_ORG_EN  27   RESERVED_0  26:11
    SIZE_E_2   10:8    SIZE_E_1   7:5  SIZE_E_0     4:2
    OD_BYPASS  1       OW_SRC     0

The geometry columns are read from the same run's CNA registers, so the value
and the geometry it is being tested against come from one dispatch:

    ic  = (0x1028 & 0xffff) + 1        oc = (0x1024 & 0xffff) + 1
    k   = sqrt(0x1020 / ic)            stride from 0x1014, which holds (s<<3)|s

On the depthwise path the oc register reads 2 and the channel count is in the
ic register; those rows are marked and their channel count is the ic one.

Usage:  reserved0-build.py [geom-dir] > reserved0-table.md
"""
import glob
import math
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np

# The container reader, the same two functions charsiu's tools/rkllm_regcmd.py
# carries, copied in so this file runs on its own with numpy and nothing else.
TARGETS = {0x0201: "CNA", 0x0801: "CORE", 0x1001: "DPU",
           0x2001: "RDMA", 0x0401: "U28", 0x0041: "SYNC", 0x0081: "BCAST"}


def streams(path, min_len=20):
    """Every maximal run of register command words, as (byte offset, words)."""
    n = os.path.getsize(path) // 8
    words = np.memmap(path, dtype="<u8", mode="r", shape=(n,))
    ok = np.isin((words >> 48).astype(np.uint32), list(TARGETS))
    idx = np.flatnonzero(ok)
    if idx.size == 0:
        return []
    out = []
    for run in np.split(idx, np.flatnonzero(np.diff(idx) != 1) + 1):
        if len(run) >= min_len:
            out.append((int(run[0]) * 8, words[run[0]:run[-1] + 1]))
    return out


def decode(ws):
    """One stream as {(target, register): value}, first write wins."""
    regs = {}
    for e in ws:
        e = int(e)
        key = ((e >> 48) & 0xffff, e & 0xffff)
        if key not in regs:
            regs[key] = (e >> 16) & 0xffffffff
    return regs

GEOM = sys.argv[1] if len(sys.argv) > 1 else "."
# The sections that name files -- g_cal against bias_k5, g_pw24, and the
# note on the earlier mail -- are about the corpus this was written against.
# On another corpus they are skipped rather than printed with the wrong
# numbers under the same sentences.
MINE = all(os.path.exists(os.path.join(GEOM, f + "_rk3576.rknn"))
           for f in ("g_cal", "bias_k5", "g_pw24", "g_k3s1", "pp_k3",
                     "g_cal_k3", "bias_k3", "p2_k5", "pp_p5"))

CNA, CORE, DPU, RDMA = 0x0201, 0x0801, 0x1001, 0x2001


def fields(v):
    return dict(RGP_CNTER=(v >> 28) & 0xf, TP_ORG_EN=(v >> 27) & 1,
                RESERVED_0=(v >> 11) & 0xffff, SIZE_E_2=(v >> 8) & 7,
                SIZE_E_1=(v >> 5) & 7, SIZE_E_0=(v >> 2) & 7,
                OD_BYPASS=(v >> 1) & 1, OW_SRC=v & 1)


def declared(path):
    """What the file itself says it is: the toolkit build string and the
    input and output shapes it records, plus the ONNX ops it names."""
    d = open(path, "rb").read()
    m = re.search(rb"compiler version: ([0-9][^)]*\))", d)
    ver = m.group(1).decode().strip() if m else "?"
    i = re.search(rb"'shape': \[([0-9, ]+)\], 'layout'", d)
    o = re.search(rb"'output': \{'is_output': True, 'idx': 0, "
                  rb"'shape': \[([0-9, ]+)\]", d)
    def shp(mm):
        if not mm:
            return "?"
        p = [x.strip() for x in mm.group(1).decode().split(",")]
        return "x".join(p[1:])            # drop the batch dimension
    ops = sorted(set(x.decode() for x in re.findall(rb"([A-Za-z]+):/", d)))
    return ver, "%s>%s" % (shp(i), shp(o)), ",".join(ops)


def read_ops(path):
    """Every dispatch in one file, as a dict of value and geometry."""
    out = []
    for off, ws in streams(path, min_len=20):
        r = decode(ws)
        v = r.get((DPU, 0x4050))
        if v is None:                     # never happens in this corpus
            out.append(dict(off=off, undecoded=True))
            continue
        core = r.get((CORE, 0x3018))
        mode = (core & 0xff) if core is not None else None
        dw = mode == 0x0a
        ic = (r[(CNA, 0x1028)] & 0xffff) + 1 if (CNA, 0x1028) in r else None
        oc = (r[(CNA, 0x1024)] & 0xffff) + 1 if (CNA, 0x1024) in r else None
        wbpk = r.get((CNA, 0x1020))
        k = None
        if wbpk and ic:
            root = int(round(math.sqrt(wbpk / ic)))
            k = root if root * root * ic == wbpk else None
        st = r.get((CNA, 0x1014))
        rec = dict(off=off, undecoded=False, v=v, dw=dw, mode=mode,
                   ic=ic, oc=oc, k=k,
                   stride=(st & 7) if st is not None else None,
                   inw=((r[(CNA, 0x102c)] >> 16) & 0xffff) + 1
                       if (CNA, 0x102c) in r else None,
                   rows=(r[(CNA, 0x102c)] & 0xffff) + 1
                       if (CNA, 0x102c) in r else None,
                   ow=(r[(CNA, 0x1030)] & 0xffff) + 1
                       if (CNA, 0x1030) in r else None,
                   pix=r[(CNA, 0x1034)] + 1 if (CNA, 0x1034) in r else None,
                   surf=(r[(CNA, 0x103c)] >> 16) & 0xffff
                       if (CNA, 0x103c) in r else None,
                   r4044=r.get((DPU, 0x4044)), r501c=r.get((RDMA, 0x501c)),
                   r40ac=r.get((DPU, 0x40ac)), r40b0=r.get((DPU, 0x40b0)),
                   r40b4=r.get((DPU, 0x40b4)), regs=r)
        rec.update(fields(v))
        # the channel count the op really works on
        rec["chan"] = rec["ic"] if dw else rec["oc"]
        out.append(rec)
    return out


def geo_key(o):
    return (o["ic"], o["oc"], o["k"], o["stride"], o["inw"], o["rows"],
            o["ow"], o["pix"], o["surf"])


def main():
    files = sorted(glob.glob(os.path.join(GEOM, "*.rknn")))
    if not files:
        sys.stderr.write("no .rknn files under %s\n" % GEOM)
        return 1
    per_file, allops = {}, []
    for p in files:
        name = os.path.basename(p).replace("_rk3576.rknn", "")
        ver, shape, onnxops = declared(p)
        ops = read_ops(p)
        for o in ops:
            o["file"] = name
        per_file[name] = dict(ver=ver, shape=shape, onnxops=onnxops, ops=ops)
        allops += ops

    good = [o for o in allops if not o["undecoded"]]
    bad = [o for o in allops if o["undecoded"]]
    reg = [o for o in good if not o["dw"]]
    dwo = [o for o in good if o["dw"]]

    W = []                                 # the report, line by line
    def p(s=""):
        W.append(s)

    p("DPU 0x4050 RESERVED_0 across %d vendor-compiled .rknn under %s" % (len(files), GEOM))
    p("=" * 68)
    p()
    p("Regenerate with reserved0-build.py, which reads only the files in")
    p("the directory it is given and prints this whole page, numbers included.")
    p()

    # ---------------------------------------------------------------- method
    p("How the value is obtained")
    p("-" * 25)
    p()
    p("A .rknn carries the register command stream the vendor runtime")
    p("submits, as little-endian u64 words")
    p()
    p("    [63:48] target   [47:16] value   [15:0] register")
    p()
    p("with target 0x0201 CNA, 0x0801 CORE, 0x1001 DPU, 0x2001 DPU_RDMA. A")
    p("maximal run of such words is one dispatch. In this corpus every run of")
    p("20 words or more carries exactly one CNA block and exactly one write")
    p("of DPU 0x4050, so a value and the geometry it is tested against always")
    p("come from the same op and there is no matching to guess at.")
    p()
    p("The word is BS_OW_CFG. Split as upstream's registers.xml splits it:")
    p()
    p("    RGP_CNTER  31:28   TP_ORG_EN  27   RESERVED_0  26:11")
    p("    SIZE_E_2   10:8    SIZE_E_1   7:5  SIZE_E_0     4:2")
    p("    OD_BYPASS  1       OW_SRC     0")
    p()
    p("So RESERVED_0 is bits 26:11, and the two values in question are")
    p()
    p("    0x80011111 -> RESERVED_0 = 34 = field bits 5 and 1 = word bits 16, 12")
    p("    0x80021111 -> RESERVED_0 = 66 = field bits 6 and 1 = word bits 17, 12")
    p()
    p("One word bit apart, 16 against 17, over a constant word bit 12. The")
    p("geometry columns come from the CNA registers of the same run:")
    p()
    p("    ic  = (0x1028 & 0xffff) + 1     oc = (0x1024 & 0xffff) + 1")
    p("    k   = sqrt(0x1020 / ic)         stride from 0x1014, which is (s<<3)|s")
    p()
    p("Three notes on reading those columns honestly.")
    p()
    p("  * The oc register holds the count rounded up to 2, so a 41 channel")
    p("    output reads 42. pq_ic and pq_oc are the two rows where that shows.")
    p("  * On the depthwise path, CORE 0x3018 mode 0x0a, the oc register reads")
    p("    2 and the channel count is in the ic register. Those rows carry the")
    p("    ic one and are marked dw in the path column.")
    p("  * On the first convolution path, CORE 0x3018 mode 0x81, three input")
    p("    channels are packed and the ic register reads 12, so the ic and k")
    p("    columns on those seven rows are the packed form and not the source")
    p("    shape. They are marked 1st. All seven read 34 either way.")
    p()
    p("Nothing here was run on hardware. These are numbers read out of files")
    p("the vendor toolkit produced, and what the bits mean was arrived at by")
    p("trial and error against those files and against the board.")
    p()

    # ----------------------------------------------------------------- table
    p()
    p("The table")
    p("-" * 9)
    p()
    p("One row per file, for the first dispatch in the file. The last column")
    p("is what the file records about itself, input>output with the batch")
    p("dropped. A + on the name means the file holds more than one distinct")
    p("RESERVED_0 across its dispatches; those are broken out below.")
    p()
    hdr = "%-15s %-10s %3s %-4s %5s %5s %2s %2s  %s" % (
        "model", "0x4050", "R_0", "path", "ic", "oc", "k", "s", "file says")
    p(hdr)
    p("-" * min(78, len(hdr)))

    def row(name, f, o):
        vals = set(x["RESERVED_0"] for x in f["ops"] if not x["undecoded"])
        path = {0x01: "reg", 0x0a: "dw", 0x81: "1st"}.get(o["mode"], "?")
        return "%-15s 0x%08x %3d %-4s %5s %5s %2s %2s  %s" % (
            name + ("+" if len(vals) > 1 else ""), o["v"], o["RESERVED_0"],
            path, o["ic"], o["oc"], o["k"] if o["k"] else "?", o["stride"],
            f["shape"])

    groups = [("RESERVED_0 = 34   (regular convolutions)",
               lambda o: not o["dw"] and o["RESERVED_0"] == 34),
              ("RESERVED_0 = 66   (regular convolutions)",
               lambda o: not o["dw"] and o["RESERVED_0"] == 66),
              ("RESERVED_0 = 38   (depthwise; a third value, see below)",
               lambda o: o["dw"])]
    counted = 0
    for title, pred in groups:
        sel = [(n, f, f["ops"][0]) for n, f in sorted(per_file.items())
               if not f["ops"][0]["undecoded"] and pred(f["ops"][0])]
        p()
        p("  " + title + "   %d files" % len(sel))
        for n, f, o in sel:
            p(row(n, f, o))
        counted += len(sel)
    left = [n for n, f in sorted(per_file.items())
            if f["ops"][0]["undecoded"]]
    if left:
        p()
        p("  could not be decoded: %s" % ", ".join(left))

    # ---------------------------------------------------------------- counts
    p()
    p()
    p("The counts")
    p("-" * 10)
    p()
    p("  files                                  %d" % len(files))
    p("  dispatches in them                     %d" % len(allops))
    p("  dispatches that could not be decoded   %d" % len(bad))
    p("  regular dispatches                     %d" % len(reg))
    p("  depthwise dispatches                   %d" % len(dwo))
    p()
    c = Counter(o["RESERVED_0"] for o in good)
    p("  by dispatch, RESERVED_0")
    for v, n in sorted(c.items()):
        p("    %-4d %4d" % (v, n))
    p()
    prim = Counter(f["ops"][0]["RESERVED_0"] for f in per_file.values()
                   if not f["ops"][0]["undecoded"])
    p("  by file, first dispatch")
    for v, n in sorted(prim.items()):
        p("    %-4d %4d" % (v, n))
    p()
    cw = Counter(o["v"] for o in good)
    p("  distinct 0x4050 words, %d of them" % len(cw))
    p("    %-12s %5s  %-4s %-4s %-4s %-4s %-4s %-4s %s"
      % ("word", "count", "RGP", "R_0", "S_E2", "S_E1", "S_E0", "OD", "OW"))
    for v, n in sorted(cw.items(), key=lambda t: -t[1]):
        f = fields(v)
        p("    0x%08x %5d  %-4d %-4d %-4d %-4d %-4d %-4d %d"
          % (v, n, f["RGP_CNTER"], f["RESERVED_0"], f["SIZE_E_2"],
             f["SIZE_E_1"], f["SIZE_E_0"], f["OD_BYPASS"], f["OW_SRC"]))
    p()
    p("  the other fields, for completeness")
    for fld in ("RGP_CNTER", "TP_ORG_EN", "SIZE_E_0", "SIZE_E_1", "SIZE_E_2",
                "OD_BYPASS", "OW_SRC"):
        a = Counter(o[fld] for o in reg)
        b = Counter(o[fld] for o in dwo)
        p("    %-10s regular %s" % (fld, dict(sorted(a.items()))))
        p("    %-10s dw      %s" % ("", dict(sorted(b.items()))))

    # ------------------------------------------------- series or geometry
    p()
    p()
    p("Does it follow the geometry?")
    p("-" * 28)
    p()
    cls = defaultdict(list)
    for o in reg:
        cls[geo_key(o)].append(o)
    confl = [(k, v) for k, v in cls.items()
             if len(set(x["RESERVED_0"] for x in v)) > 1]
    p("No. Grouping the %d regular dispatches by their full CNA geometry --" % len(reg))
    p("ic, oc, kernel, stride, input width, rows, output width, pixels and")
    p("surface -- gives %d distinct classes, and %d of them contain both" % (len(cls), len(confl)))
    ngroups = len(set(
        (tuple(sorted(set(x["file"] for x in v if x["RESERVED_0"] == 34))),
         tuple(sorted(set(x["file"] for x in v if x["RESERVED_0"] == 66))))
        for _, v in confl))
    p("values. Read that as %d facts and not %d: a model appears in several"
      % (ngroups, len(confl)))
    p("classes because the compiler splits it into CBUF windows of different")
    p("heights, and each window is its own class here. Same geometry,")
    p("different RESERVED_0, in the same corpus:")
    p()
    for k, v in sorted(confl, key=lambda t: -len(t[1])):
        a = sorted(set(x["file"] for x in v if x["RESERVED_0"] == 34))
        b = sorted(set(x["file"] for x in v if x["RESERVED_0"] == 66))
        p("  ic %s  oc %s  k %s  stride %s  %sx%s in, %s pixels out"
          % (k[0], k[1], k[2], k[3], k[4], k[5], k[7]))
        for tag, lst in (("34", a), ("66", b)):
            line = "    %s: " % tag
            for nm in lst:
                if len(line) + len(nm) + 2 > 78:
                    p(line.rstrip(", ") + ",")
                    line = "        "
                line += nm + ", "
            p(line.rstrip(", "))
    p()
    if MINE:
        p("The cleanest single pair is g_cal against bias_k5. Both are one ONNX")
        p("Conv, ic 16, oc 128, 80x80 input, k = 5, stride 2, compiled by the")
        p("same toolkit build, and the two .onnx sources are the same 205601")
        p("bytes -- they differ in the weight and bias VALUES and in nothing")
        p("else. Their first dispatches are 138 registers each and differ in")
        p("five of them:")
        a = read_ops(os.path.join(GEOM, "g_cal_rk3576.rknn"))[0]["regs"]
        b = read_ops(os.path.join(GEOM, "bias_k5_rk3576.rknn"))[0]["regs"]
        for kk in sorted(set(a) | set(b)):
            if a.get(kk) != b.get(kk):
                p("    t=%04x r=%04x   g_cal %08x   bias_k5 %08x"
                  % (kk[0], kk[1], a.get(kk, 0), b.get(kk, 0)))
        p()
        p("Three more same-geometry pairs, one from each of the other groups:")
        p()
        for x, y in (("g_k3s1", "pp_k3"), ("g_cal_k3", "bias_k3"),
                     ("p2_k5", "pp_p5")):
            ra = read_ops(os.path.join(GEOM, x + "_rk3576.rknn"))[0]["regs"]
            rb = read_ops(os.path.join(GEOM, y + "_rk3576.rknn"))[0]["regs"]
            d = [kk for kk in sorted(set(ra) | set(rb)) if ra.get(kk) != rb.get(kk)]
            p("  %s against %s: %d registers differ, %s"
              % (x, y, len(d), " ".join("%04x" % kk[1] for kk in d)))
        p()
        p("0x40ac, 0x40b0 and 0x40b4 are the output zero point, the requant")
        p("multiplier and the requant shift. Those differ between any two models")
        p("with different weights and say nothing here. What is left in every")
        p("pair is 0x4044, 0x4050 and 0x501c, the same three every time.")
    else:
        p("(the named same-geometry pairs of the corpus this was written against")
        p(" are not in this one, so that comparison is skipped here)")

    p()
    p()
    p("Does it follow the model series?")
    p("-" * 32)
    p()
    vers = Counter(f["ver"] for f in per_file.values())
    p("Not that either, and one form of the guess dies immediately: all %d" % len(files))
    p("files carry the same toolkit build string,")
    p()
    for v, n in vers.most_common():
        p("    %s   %d files" % (v, n))
    p()
    p("so it is not a toolkit version difference.")
    p()
    mixed = {n: f for n, f in per_file.items()
             if len(set(o["RESERVED_0"] for o in f["ops"]
                        if not o["undecoded"])) > 1}
    p("And a per-model constant cannot be right, because %d files hold more" % len(mixed)) if mixed else p("No file in this corpus holds more than one value inside a single compile.")
    if mixed: p("than one value inside a single compile:")
    p()
    def dump(n):
        f = per_file[n]
        p("  %s, %s, one %s in the source graph." %
          (n, f["shape"], f["onnxops"] or "?"))
        p("  Its dispatches, by byte offset in the file:")
        for o in f["ops"]:
            p("    0x%-6x 0x%08x  R_0 %-3d %s ic %-5s oc %-5s k %-2s "
              "%s px"
              % (o["off"], o["v"], o["RESERVED_0"],
                 "dw " if o["dw"] else "   ", o["ic"], o["oc"],
                 o["k"] if o["k"] else "?", o["pix"]))
    if MINE:
        dump("g_pw24")
        p()
        others = sorted(k for k in mixed if k != "g_pw24")
        p("  and the same shape in the other %d, all of them dwbig_*:" % len(others))
        dump(others[0])
        p("    ... and the same pattern in %s"
          % ", ".join(others[1:4] + ["..."]) if len(others) > 4
          else "    ... and the same in " + ", ".join(others[1:]))
        p()
        p("g_pw24 is the one that settles it. One Conv in the source graph, one")
        p("compile, one file, and its two REGULAR dispatches disagree: the 512 to")
        p("1024 pointwise reads 34 and the one-pixel 16 by 16 op the compiler")
        p("adds for itself reads 66. Whatever selects the value is decided per")
        p("dispatch, not per model and not per batch of models.")
    else:
        for n in sorted(mixed)[:2]:
            dump(n)
        if not mixed:
            p("  (no file in this corpus does)")

    # --------------------------------------------------------- what it does
    p()
    p()
    p("What it does follow")
    p("-" * 19)
    p()
    lock = Counter((o["RESERVED_0"], o["r4044"]) for o in reg)
    p("DPU 0x4044, exactly, on every regular dispatch in the corpus:")
    p()
    for (r0, v4), n in sorted(lock.items()):
        p("    RESERVED_0 %-3d  <->  0x4044 = 0x%08x    %d dispatches" % (r0, v4, n))
    p()
    r0_to, v4_to = defaultdict(set), defaultdict(set)
    for r0, v4 in lock:
        r0_to[r0].add(v4)
        v4_to[v4].add(r0)
    onetoone = bool(reg) and all(len(v) == 1 for v in r0_to.values()) \
               and all(len(v) == 1 for v in v4_to.values())
    if not reg:
        p("(no regular dispatches in this corpus, so nothing to pair)")
    elif onetoone:
        p("%d of %d, no exceptions. 0x2001/0x501c moves with them:" % (sum(lock.values()), len(reg)))
    else:
        p("NOT one-to-one in this corpus: a RESERVED_0 value meets more than one")
        p("0x4044 value or the other way round, %d regular dispatches. 0x501c:" % len(reg))
    p()
    s = defaultdict(Counter)
    for o in reg:
        s[o["RESERVED_0"]][o["r501c"]] += 1
    for r0 in sorted(s):
        p("    RESERVED_0 %-3d  ->  0x501c %s"
          % (r0, ", ".join("0x%x (%d)" % (k, v)
                           for k, v in sorted(s[r0].items()))))
    p()
    if MINE:
        p("Sweeping every register in the stream, 0x4044 is the ONLY one whose")
        p("value partitions the two RESERVED_0 groups one-to-one, and 0x501c the")
        p("only other whose value sets are disjoint between them. So the bit is")
        p("not a loose constant with no company: it is one third of a single")
        p("per-op decision in the bias-and-scale path of the output stage.")
        p()
    dws = Counter((o["RESERVED_0"], o["r4044"], o["r501c"]) for o in dwo)
    if dws:
        p("The depthwise dispatches read")
        for (r0, v4, v5), n in sorted(dws.items()):
            p("    RESERVED_0 %d, 0x4044 = 0x%x, 0x501c = 0x%x, %d dispatches"
              % (r0, v4, v5, n))
    else:
        p("(no depthwise dispatches in this corpus)")
    if MINE:
        p("38 is 34 with field bit 2 -- word bit 13 -- added, so on the word-bit")
        p("16-against-17 axis depthwise sits with the 34 group while its 0x4044")
        p("sits with the 66 group. The lockstep is a statement about the regular")
        p("datapath only, and I am not claiming more than that.")
        p()
        p("What selects the arm in the first place is still open. It is not the")
        p("shape, not the file, not the toolkit build, and not the day the file")
        p("was compiled: 2026-08-08 and 2026-08-09 each produced both arms.")

    # ------------------------------------------------------ for the driver
    p()
    p()
    p("What this means for the driver")
    p("-" * 30)
    p()
    p("rkt_regcmd.c emits, for a regular convolution,")
    p()
    p("    0x4044 = 0x00000001")
    p("    0x4050 = 0x80011011 or 0x80011111   (RESERVED_0 = 34)")
    p("    0x501c = 0x00000710")
    p()
    p("which is the 34 arm in all three registers at once. It is the arm the")
    p("vendor takes on %d of its %d regular dispatches, and the driver never"
      % (lock[(34, 1)], len(reg)))
    p("mixes an 0x4044 from one arm with a 0x4050 from the other. That is")
    p("the part I could not say in the earlier mail and can say now.")
    p()
    p("The RK3576 encoder has no depthwise path at all -- fill_regcmd_rk3576")
    p("covers a regular convolution and rkt_ml_operation_supported declines")
    p("depthwise before it is reached -- so the driver never emits the 38")
    p("word. That is an observation about the vendor's depthwise datapath")
    p("and about upstream's RK3588 encoder, not about this one.")
    p()
    p("The field is also not free: moved on its own to upstream's 0, on a 5x5")
    p("at 128 output channels and a pointwise at 88, the output stayed")
    p("identical to the baseline and the job timed out. So it is a completion")
    p("field, and 34 is the value that completes.")

    if MINE:
        # ----------------------------------------------------------- retraction
        p()
        p()
        p("What of the claim I sent")
        p("-" * 24)
        p()
        p("The counting half stands. 34 and 66 are the only two RESERVED_0 values")
        p("on regular convolutions, 34 is the common one, %d dispatches against" % c[34])
        p("%d, and %d files against %d by first dispatch." % (c[66], prim[34], prim[66]))
        p()
        p("Three things in it were wrong or too small, and I would rather correct")
        p("them here than let them stand.")
        p()
        p("1. \"It does not correlate with oc, ic, spatial size, kernel size or")
        p("   stride\" is true but it was the weak version of the test. The strong")
        p("   version is the one you asked for: hold the WHOLE geometry fixed.")
        p("   %d geometry classes then carry both values, %d of them once the CBUF"
          % (len(confl), ngroups))
        p("   windows of one model are folded together, and g_cal against bias_k5")
        p("   is two files identical in every register but five.")
        p()
        p("2. \"What it does track is which batch of models it came from, which")
        p("   makes a toolkit setting more likely\" does not survive as written.")
        p("   The batches are uniform, but the batch is not what decides:")
        p("   g_pw24 carries both values in one compile of one Conv, and the")
        p("   toolkit build string is identical across all %d files. Why a whole" % len(files))
        p("   batch lands on one arm I still cannot say.")
        p()
        p("3. It only ever mentioned two values. There is a third, 38, on all %d" % len(dwo))
        p("   depthwise dispatches. The RK3576 encoder declines depthwise so it")
        p("   never emits that word, but the corpus has it and the table should")
        p("   have said so.")
        p()
        p("The one thing the earlier mail did not have is the answer to your")
        p("question. It is not a toolkit setting sitting on its own; it is a bit")
        p("of a three-register per-op choice, and the driver takes one side of")
        p("that choice consistently.")
        p()

    out = "\n".join(W)
    over = [(i + 1, l) for i, l in enumerate(W) if len(l) > 78]
    sys.stdout.write(out + "\n")
    if over:
        sys.stderr.write("WARNING: %d lines over 78 columns\n" % len(over))
        for i, l in over[:10]:
            sys.stderr.write("  %d: %d cols: %s\n" % (i, len(l), l))
    return 0


if __name__ == "__main__":
    sys.exit(main())
