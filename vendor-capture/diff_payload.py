#!/usr/bin/env python3
"""
Diff the vendor (rknpu) NPU payload against Mesa's, for the simplest conv --
working purely from the two SERIAL-CONSOLE logs (no USB / no binary transfer).

Both stacks print their BOs as text in the same "cap: BO" format:
  vendor kernel: "rknpu cap: BO weights len=N distinct=D nonzero=Z"
                 "rknpu cap: BO weights +0000: 80 81 .."
  mesa script  : "mesa cap: BO weights len=N distinct=D nonzero=Z filesize=F"
                 "mesa cap: BO weights +0000: 7f 81 .."

The two come from the same source conv (conv2d.tflite: Mesa runs it directly,
the vendor runs conv2d_rk3576.rknn built from its weights). The two toolkits
re-quantize independently, so weight *bytes* differ; the comparison is therefore
structural -- per BO: distinct / nonzero over the same window, and the hex head
byte-for-byte (the input BO, fed the identical i%251 ramp, should match exactly;
weights should match in structure if the packing is the same).

One combined serial log works too (pass it once): vendor lines are tagged
"rknpu cap:", mesa lines "mesa cap:", so they're split by prefix.

Usage: diff_payload.py <vendor-log.txt> [<mesa-log.txt>]
"""
import re
import sys

BO_NAMES = ["weights", "input", "bias", "output"]


def parse_log(path, prefix):
    """Return {name: {win, distinct, nonzero, head}} for lines '<prefix> cap:'.

    Robust to the garbled/duplicated serial console: hex rows are accumulated by
    (name, offset) so a re-seen offset just overwrites with the same bytes, and
    header lines (stats) are kept in a separate map so they never clobber the
    accumulated hex head. Rows are matched before headers (a '+OFFS:' line never
    carries len=, but a merged line might -- prefer the row reading).
    """
    tag = f"{prefix} cap: BO"
    hdr = re.compile(
        re.escape(prefix) +
        r" cap:\s+BO\s+(\w+)\s+.*?len=(\d+)\s+distinct=(\d+)\s+nonzero=(\d+)")
    row = re.compile(
        re.escape(prefix) +
        r" cap:\s+BO\s+(\w+)\s+\+([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2} ?){1,16})")
    rows = {}    # name -> {offset: bytes}
    stats = {}   # name -> (win, distinct, nonzero)
    with open(path, "r", errors="replace") as f:
        for line in f:
            if tag not in line:
                continue
            r = row.search(line)
            if r:
                name = r.group(1)
                off = int(r.group(2), 16)
                vals = bytes(int(x, 16) for x in r.group(3).split())
                rows.setdefault(name, {})[off] = vals
                continue
            m = hdr.search(line)
            if m:
                stats[m.group(1)] = (int(m.group(2)), int(m.group(3)),
                                     int(m.group(4)))
    bos = {}
    for name in set(rows) | set(stats):
        win, distinct, nonzero = stats.get(name, (0, 0, 0))
        head = bytearray()
        for off in sorted(rows.get(name, {})):
            if len(head) < off:
                head.extend(b"\x00" * (off - len(head)))
            v = rows[name][off]
            head[off:off + len(v)] = v
        bos[name] = dict(win=win, distinct=distinct, nonzero=nonzero,
                         head=bytes(head))
    return bos


def cmp_head(a, b):
    n = min(len(a), len(b))
    if n == 0:
        return 0, -1, 0.0
    first = -1
    same = 0
    for i in range(n):
        if a[i] == b[i]:
            same += 1
        elif first < 0:
            first = i
    return n, first, 100.0 * same / n


def main():
    if len(sys.argv) < 2:
        print("usage: diff_payload.py <vendor-log.txt> [<mesa-log.txt>]")
        sys.exit(1)
    vendor_log = sys.argv[1]
    mesa_log = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
    vendor = parse_log(vendor_log, "rknpu")
    mesa = parse_log(mesa_log, "mesa")
    if not vendor:
        print("no 'rknpu cap: BO' lines in", vendor_log); sys.exit(1)
    if not mesa:
        print("no 'mesa cap: BO' lines in", mesa_log); sys.exit(1)

    for name in BO_NAMES:
        print("=" * 72)
        print(f"BO: {name}")
        v = vendor.get(name)
        m = mesa.get(name)
        if not v:
            print("  vendor: <not captured>")
        if not m:
            print("  mesa:   <not captured>")
        if not v or not m:
            continue

        print(f"  vendor: win={v['win']} distinct={v['distinct']} "
              f"nonzero={v['nonzero']} head={len(v['head'])}B")
        print(f"  mesa:   win={m['win']} distinct={m['distinct']} "
              f"nonzero={m['nonzero']} head={len(m['head'])}B")
        print(f"  -- distinct: vendor={v['distinct']} mesa={m['distinct']} "
              f"({'MATCH' if v['distinct'] == m['distinct'] else 'DIFFER'})")
        vp = 100.0 * v['nonzero'] / v['win'] if v['win'] else 0
        mp = 100.0 * m['nonzero'] / m['win'] if m['win'] else 0
        print(f"  -- nonzero%: vendor={vp:.1f}% mesa={mp:.1f}% "
              f"({'~same' if abs(vp - mp) < 2 else 'DIFFER'})")

        n, fd, pct = cmp_head(v['head'], m['head'])
        if n == 0:
            print("  -- head: <no hex head on one side>")
        elif fd < 0:
            print(f"  -- head[{n}B]: IDENTICAL ({pct:.1f}%)")
        else:
            print(f"  -- head[{n}B]: {pct:.1f}% byte-match, first diff at "
                  f"+0x{fd:x} (vendor={v['head'][fd]:02x} mesa={m['head'][fd]:02x})")
        print(f"     vendor head: {v['head'][:32].hex(' ')}")
        print(f"     mesa   head: {m['head'][:32].hex(' ')}")
    print("=" * 72)


if __name__ == "__main__":
    main()
