#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Is the regcmd read at all on the submits that compute nothing?

Igor Paunovic asked this on the v4 thread (2026-08-03). Every measurement so far
is either what the driver wrote or what the registers hold at completion, and
neither can separate "fetched and ignored" from "never fetched". The regcmd is
DMA'd, so it is the one part of the path with a read side we can observe.

Method: rocket.regcmd_probe is a one-shot. Arm it and the next submit gets
PC_BASE_ADDRESS pointed at an iova nothing is mapped at. If the block fetches,
rk_iommu has to log a page fault at that exact address. Silence means no fetch.

Order matters. The question is asked while the wall is actually in effect, and
the positive control comes afterwards:

  1. A          must be OK        establishes the baseline
  2. B          must be WRONG     establishes the wall
  3. B poisoned THE QUESTION      fault -> fetched and ignored
                                  no fault -> never fetched
  4. A          must be OK        the poisoned job was recovered
  5. A poisoned POSITIVE CONTROL  a fault MUST appear here

If step 5 shows no fault, the probe cannot see fetches at all and step 3's
silence means nothing. Read them together or not at all.

The poisoned job is expected to fail. It either times out and goes through the
scheduler reset, or it comes back wrong. Both are fine, the output of a poisoned
run is not the measurement.

Usage: TEFLON_LIB=... python3 test_probe.py <modelA> <modelB>
"""
import os
import subprocess
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_a, model_b = sys.argv[1], sys.argv[2]
PARAM = "/sys/module/rocket/parameters/regcmd_probe"


def ref_for(path):
    det = tflite.Interpreter(model_path=path)
    det.allocate_tensors()
    inp = det.get_input_details()[0]
    out = det.get_output_details()[0]
    n = int(np.prod(inp["shape"]))
    indata = (np.arange(n) % 251).astype(np.int64)
    det.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    det.invoke()
    cpu = det.get_tensor(out["index"])[0].flatten().astype(int)
    oq = out.get("quantization", (0.0, 0))
    zp = int(oq[1]) if oq and len(oq) > 1 else 128
    return indata, np.maximum(cpu, zp), zp


def npu_interp(path):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    it = tflite.Interpreter(model_path=path, experimental_delegates=deleg)
    it.allocate_tensors()
    return it


def run(it, indata):
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    it.invoke()
    return it.get_tensor(out["index"])[0].flatten().astype(int)


def kmsg():
    try:
        return subprocess.run(["dmesg"], capture_output=True, text=True).stdout.splitlines()
    except Exception:
        return []


def arm():
    with open(PARAM, "w") as f:
        f.write("1\n")


def report(mark, before):
    """Everything the kernel said since `before`, filtered to what matters."""
    new = kmsg()[len(before):]
    poison = [l for l in new if "regcmd_probe:" in l]
    faults = [l for l in new if "age fault" in l or "iommu" in l.lower()]
    for l in poison:
        print(f"    {l.strip()}", flush=True)
    if not poison:
        print("    (the probe did not fire, no submit happened?)", flush=True)
    for l in faults[:8]:
        print(f"    {l.strip()}", flush=True)
    addr = None
    for l in poison:
        if "unmapped 0x" in l:
            addr = l.split("unmapped 0x")[1].split()[0].rstrip(",")
    hit = any(addr and addr.lstrip("0").lower() in l.lower().replace("0x", "")
              for l in faults) if addr else False
    print(f"    {mark}: poison iova {addr}, "
          f"{len(faults)} iommu line(s), match={'YES' if hit else 'no'}", flush=True)
    return hit


in_a, ref_a, zp_a = ref_for(model_a)
in_b, ref_b, zp_b = ref_for(model_b)

print(f"=== A={os.path.basename(model_a)} (zp {zp_a})  "
      f"B={os.path.basename(model_b)} (zp {zp_b}) ===", flush=True)

if not os.path.exists(PARAM):
    print("  regcmd_probe not present, this kernel does not carry the probe", flush=True)
    sys.exit(0)

it_a = npu_interp(model_a)
it_b = npu_interp(model_b)


def step(tag, it, indata, ref):
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    ok = md <= 2
    print(f"  {tag}: distinct={len(np.unique(got)):3d} maxdiff={md:3d}  "
          f"{'OK' if ok else 'WRONG'}", flush=True)
    return ok


a_ok = step("1 A        ", it_a, in_a, ref_a)
b_bad = not step("2 B        ", it_b, in_b, ref_b)

print("  3 B poisoned  THE QUESTION", flush=True)
before = kmsg()
arm()
try:
    step("    B'       ", it_b, in_b, ref_b)
except Exception as e:
    print(f"    invoke raised {type(e).__name__}: {e}", flush=True)
q_hit = report("QUESTION", before)

a2_ok = step("4 A        ", it_a, in_a, ref_a)

print("  5 A poisoned  POSITIVE CONTROL", flush=True)
before = kmsg()
arm()
try:
    step("    A'       ", it_a, in_a, ref_a)
except Exception as e:
    print(f"    invoke raised {type(e).__name__}: {e}", flush=True)
c_hit = report("CONTROL ", before)

print("", flush=True)
if not (a_ok and b_bad):
    print("  VERDICT: preconditions not met (need A ok and B wrong). The wall was not",
          flush=True)
    print("           in effect this run, so neither probe means anything.", flush=True)
elif not c_hit:
    print("  VERDICT: the positive control raised no fault, so the probe cannot see a",
          flush=True)
    print("           fetch at all. Step 3 is uninterpretable. Fix the probe first.",
          flush=True)
elif q_hit:
    print("  VERDICT: the walled submit DOES fetch its regcmd. The bytes reach the",
          flush=True)
    print("           block and are ignored. The bank is not the story.", flush=True)
else:
    print("  VERDICT: the walled submit NEVER fetches its regcmd, while a working one",
          flush=True)
    print("           does. The block is not reloading its configuration at all.",
          flush=True)

sys.stdout.flush()
os._exit(0)
