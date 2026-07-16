#!/usr/bin/env python3
"""
Split + diff the vendor ordered writel trace (vendor_wt.trace pulled from the
board's /opt/npu-cap/). Lines look like:
    rknpu wt <seq> <off> <val> <caller>
Groups writes into contiguous blocks by caller. The per-submit PC kick is the
run of caller == rknpu_job_subcore_commit_pc; writes before the first such block
are the cold-start arming (power_on / state_init). We then diff submit#0's kick
against submit#1's (ORDER included) -- the dimension the value-only writel-audit
never covered -- and list what the cold-start arming does that the warm submits
don't re-issue (yet the warm submits still MAC correctly => that state latches).

Usage:  python3 split_wt.py vendor_wt.trace
"""
import sys, re

path = sys.argv[1] if len(sys.argv) > 1 else "vendor_wt.trace"
rx = re.compile(r"rknpu wt (\d+)\s+(\S+)\s+(\S+)\s+(\S+)")
writes = []
for ln in open(path, errors="replace"):
    m = rx.search(ln)
    if m:
        writes.append((int(m.group(1)), m.group(2), m.group(3), m.group(4)))
writes.sort(key=lambda w: w[0])
if not writes:
    print("no 'rknpu wt' lines in", path); sys.exit(1)

# contiguous blocks by caller
blocks = []
for seq, off, val, fn in writes:
    if not blocks or blocks[-1]["fn"] != fn:
        blocks.append({"fn": fn, "w": []})
    blocks[-1]["w"].append((off, val))

print(f"== {len(writes)} writes in {len(blocks)} caller-blocks ==")
for i, b in enumerate(blocks):
    print(f"  block {i:2d}  {len(b['w']):4d} writes  <- {b['fn']}")

KICK = [b for b in blocks if "commit_pc" in b["fn"]]
print(f"\n== {len(KICK)} commit_pc kick blocks (= submits) ==")


def show(b, label):
    print(f"\n-- {label} ({len(b['w'])} writes) --")
    for off, val in b["w"]:
        print(f"   {off:>8} = {val}")


if len(KICK) >= 2:
    s0, s1 = KICK[0]["w"], KICK[1]["w"]
    print(f"\n== DIFF submit#0 vs submit#1 kick (order-sensitive) ==")
    if s0 == s1:
        print("  IDENTICAL (same offsets, same values, same ORDER).")
        print("  => the re-arm is NOT in the driver's per-submit register stream.")
        print("     Points at the completion/fence path or HW-latched state, not writes.")
    else:
        import difflib
        a = [f"{o}={v}" for o, v in s0]
        b = [f"{o}={v}" for o, v in s1]
        for line in difflib.unified_diff(a, b, "submit0", "submit1", lineterm=""):
            print("  " + line)
        print("  => the delta above is what the warm 2nd submit does differently.")
    show(KICK[0], "submit#0 kick")
    show(KICK[1], "submit#1 kick")
else:
    print("  <2 commit_pc blocks found -- dumping all blocks for manual inspection")
    for i, b in enumerate(blocks):
        show(b, f"block{i} {b['fn']}")

# cold-start arming = everything before the first kick block
pre = []
for b in blocks:
    if "commit_pc" in b["fn"]:
        break
    pre += [(o, v, b["fn"]) for o, v in b["w"]]
if pre:
    print(f"\n== cold-start arming (before submit#0 kick, {len(pre)} writes) ==")
    for off, val, fn in pre:
        print(f"   {off:>8} = {val:>12}   {fn}")
    print("  (warm submits 1..4 MAC correctly WITHOUT re-issuing these => this state latches for the session)")
