#!/usr/bin/env python3
"""
Find rknpu_task descriptors in a .rknn and print enable_mask / int_mask /
int_clear etc. These are the per-task PC-submit values the vendor kernel writes
(INT_MASK/INT_CLEAR/enable_mask) that rocket does not replicate.

struct rknpu_task (__packed, 40 bytes):
  0  u32 flags
  4  u32 op_idx
  8  u32 enable_mask
  12 u32 int_mask
  16 u32 int_clear
  20 u32 int_status
  24 u32 regcfg_amount
  28 u32 regcfg_offset
  32 u64 regcmd_addr

Strategy: scan for a plausible regcfg_amount (the regcmd entry count we know,
~139) at struct offset 24, validate the surrounding fields, print the struct.

Usage: extract_task.py <file.rknn> [expected_amount]
"""
import sys, struct

def main():
    path = sys.argv[1]
    want = int(sys.argv[2]) if len(sys.argv) > 2 else 139
    data = open(path, "rb").read()
    n = len(data)
    found = 0
    for amt_off in range(0, n - 16, 4):
        amt = struct.unpack_from("<I", data, amt_off)[0]
        if abs(amt - want) > 8 or amt == 0:
            continue
        s = amt_off - 24            # struct start
        if s < 0 or s + 40 > n:
            continue
        flags, op_idx, en, im, ic, istat, ra, roff = struct.unpack_from("<8I", data, s)
        rcmd = struct.unpack_from("<Q", data, s + 32)[0]
        # validate: int_status usually 0, regcfg_amount==amt, en/im look like masks
        if istat != 0 or ra != amt:
            continue
        found += 1
        print("==== rknpu_task @ file offset 0x%x (regcfg_amount=%d) ====" % (s, amt))
        print("  flags        = 0x%08x" % flags)
        print("  op_idx       = %d" % op_idx)
        print("  enable_mask  = 0x%08x   <-- 0xf008 GLOBAL_OP_ENABLE value" % en)
        print("  int_mask     = 0x%08x   <-- written to PC INT_MASK(0x20)" % im)
        print("  int_clear    = 0x%08x   <-- written to PC INT_CLEAR(0x24)" % ic)
        print("  int_status   = 0x%08x" % istat)
        print("  regcfg_amount= %d" % ra)
        print("  regcfg_offset= 0x%08x" % roff)
        print("  regcmd_addr  = 0x%016x" % rcmd)
        print()
        if found >= 12:
            break
    if not found:
        print("no task descriptor found near amount=%d; try a different value"
              " (check the regcmd run length from extract_regcmd.py)" % want)

if __name__ == "__main__":
    main()
