#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# diff_writel_trace.py  (rk3576-writel-trace)
#
# Align a VENDOR rknpu NPU-register write trace against a ROCKET write trace and
# report writes the vendor makes that rocket does NOT (or makes in a different
# order). Both traces are produced by the rk3576-writel-trace kernel builds:
#
#   vendor:  echo 1 > /sys/module/rknpu/parameters/wtrace   ; run one inference
#   rocket:  echo 1 > /sys/module/rocket/parameters/wtrace  ; run one inference
#
# Each write is logged (see rknpu_wtrace_emit / rocket_wtrace_emit) as:
#   rknpu  wt <seq> <off> <val> <caller>
#   rocket wt <seq> <off> <val> <caller>
# where <off> is the register's ABSOLUTE offset in the NPU window (both stacks
# use the same absolute offsets, so the two traces are directly diffable).
#
# Usage:
#   diff_writel_trace.py VENDOR_LOG ROCKET_LOG [--key off|offval] [--no-drop]
#
# VENDOR_LOG / ROCKET_LOG are dmesg captures (console garble / timestamp
# prefixes tolerated). Grep is not required; the parser finds "wt" records
# anywhere in a line.
# ---------------------------------------------------------------------------
import re
import sys
import argparse
from difflib import SequenceMatcher

# absolute-offset -> human name (RK3576 NPU register window)
REGS = {
    0x0008: "PC_OP_EN",
    0x0010: "PC_DATA_ADDR",      # regcmd base ptr (0x1 = slave-mode toggle)
    0x0014: "PC_DATA_AMOUNT",
    0x0020: "PC_INT_MASK",
    0x0024: "PC_INT_CLEAR",
    0x0030: "PC_TASK_CON",       # ((0x6|pp)<<16)|task_number
    0x0034: "PC_DMA_BASE_ADDR",  # task-descriptor base (0 in every capture)
    0x1004: "CNA_S_POINTER",     # 0xe = PP_MODE|EXECUTER_PP_EN|POINTER_PP_EN
    0x1024: "CNA_DATA_SIZE1",    # 0x80000000 = activate PP group
    0x2210: "TOP_PERF_CLR",
    0x2410: "CORE_PERF_CLR",
    0x3004: "CORE_S_POINTER",
    0x4004: "DPU_S_POINTER",
    0x5004: "RDMA_S_POINTER",
}

# instrumentation writes emitted only by the vendor CAPTURE build (est/armdbg
# blocks in rknpu_job_subcore_commit_pc), NOT by the real driver path. Dropped
# by default so the diff reflects genuine driver writes.
INSTRUMENTATION = {
    (0x0024, 0x30000000),   # est: pre-clear stale PC_DONE before the sample loop
}

WT_RE = re.compile(r"\bwt\s+(\d+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)")


def name(off):
    return REGS.get(off, "?")


def parse(path, drop_instrumentation=True):
    """Return [(off, val, fn)] in sequence order."""
    out = []
    seen_seq = set()
    with open(path, "r", errors="replace") as f:
        for line in f:
            m = WT_RE.search(line)
            if not m:
                continue
            seq = int(m.group(1))
            off = int(m.group(2), 16)
            val = int(m.group(3), 16)
            fn = m.group(4)
            # console garble can duplicate a line; de-dupe on seq.
            if seq in seen_seq:
                continue
            seen_seq.add(seq)
            if drop_instrumentation and (off, val) in INSTRUMENTATION:
                continue
            out.append((seq, off, val, fn))
    out.sort(key=lambda r: r[0])
    return [(off, val, fn) for (_seq, off, val, fn) in out]


def fmt(rec):
    off, val, fn = rec
    return f"{off:#06x} {name(off):<16} = {val:#010x}   [{fn}]"


def main():
    ap = argparse.ArgumentParser(description="diff vendor vs rocket NPU writel traces")
    ap.add_argument("vendor")
    ap.add_argument("rocket")
    ap.add_argument("--key", choices=["off", "offval"], default="off",
                    help="align on offset only (default) or offset+value")
    ap.add_argument("--no-drop", action="store_true",
                    help="keep the vendor capture-build instrumentation writes")
    args = ap.parse_args()

    v = parse(args.vendor, drop_instrumentation=not args.no_drop)
    r = parse(args.rocket, drop_instrumentation=not args.no_drop)

    def key(rec):
        return rec[0] if args.key == "off" else (rec[0], rec[1])

    vk = [key(x) for x in v]
    rk = [key(x) for x in r]

    print(f"# vendor writes: {len(v)}   rocket writes: {len(r)}   (key={args.key})")
    print("# ---- aligned sequence diff (V=vendor-only, R=rocket-only) ----")
    sm = SequenceMatcher(a=vk, b=rk, autojunk=False)
    vendor_only = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            for x in v[i1:i2]:
                print("  V-only  ", fmt(x))
                vendor_only.append(x)
        if tag in ("insert", "replace"):
            for x in r[j1:j2]:
                print("  R-only  ", fmt(x))

    print("# ---- multiset summary: register offsets the VENDOR writes ----")
    from collections import Counter
    vc = Counter(x[0] for x in v)
    rc = Counter(x[0] for x in r)
    alloff = sorted(set(vc) | set(rc))
    print(f"  {'off':>7} {'name':<16} {'vendor':>7} {'rocket':>7}   flag")
    for off in alloff:
        flag = ""
        if vc[off] and not rc[off]:
            flag = "<== vendor writes this, rocket NEVER"
        elif rc[off] and not vc[off]:
            flag = "(rocket-only)"
        print(f"  {off:#07x} {name(off):<16} {vc[off]:>7} {rc[off]:>7}   {flag}")

    missing = sorted(set(vc) - set(rc))
    print("# ---- VERDICT ----")
    if missing:
        print("  Vendor writes these offsets that rocket NEVER writes:",
              ", ".join(f"{o:#x}({name(o)})" for o in missing))
    else:
        print("  No register offset is written by the vendor and never by rocket.")
        print("  (Any difference is in ORDER/COUNT/VALUE or in regcmd content, not a")
        print("   missing kernel register write.)")


if __name__ == "__main__":
    main()
