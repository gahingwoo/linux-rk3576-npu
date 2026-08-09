#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
"""
Is the walled submit a no-op, or a re-run of the RESIDENT configuration?

Igor Paunovic raised this on the v5 thread. Marking the failing job's own output
BO and finding it untouched says the block did not write THERE. It does not say
the block wrote nothing: everything measured is equally consistent with the block
still executing the last configuration it loaded, and writing to the PREVIOUS
task's addresses.

So mark the resident job's buffer instead:

  1. invoke A            A computes, kernel stashes A's output BO
  2. mark_prev=0xa5      fill A's output BO with the marker, right now
  3. check_watch=0xa5    must be ~100%, the marker is in place
  4. invoke B            the submit that walls
  5. check_watch=0xa5    THE QUESTION
       marker gone       -> B's submit re-ran A's configuration and wrote to A's
                            addresses. Not a no-op, and the question becomes why
                            the fetch stops after the first post-reset submit.
       marker survives   -> nothing wrote A's buffer either, the no-op reading
                            stands.
  6. invoke A            CONTROL: A must compute correctly again, and
  7. check_watch=0xa5    must be ~0%, since A just wrote its own buffer. If the
                         marker survives here the check cannot see writes at all
                         and step 5 means nothing.

Usage: TEFLON_LIB=... python3 test_mirror.py <A> <B>
"""
import os
import subprocess
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_a, model_b = sys.argv[1], sys.argv[2]
P = "/sys/module/rocket/parameters"
MARKER = 0xA5


def w(name, val):
    with open(f"{P}/{name}", "w") as f:
        f.write(str(val) + "\n")


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


def npu(path):
    d = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    it = tflite.Interpreter(model_path=path, experimental_delegates=d)
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


def check(tag):
    """Write check_watch and return the surviving percentage the kernel reports."""
    before = len(kmsg())
    w("check_watch", MARKER)
    pct = None
    for l in kmsg()[before:]:
        if "check_watch:" in l or "mark_prev:" in l:
            print(f"    {l.strip()}", flush=True)
            if "survives in" in l and "(" in l:
                try:
                    pct = int(l.rsplit("(", 1)[1].split("%")[0])
                except (ValueError, IndexError):
                    pass
    print(f"  {tag}: marker survives {pct if pct is not None else '?'}%", flush=True)
    return pct


if not os.path.exists(f"{P}/mark_prev"):
    print("  rocket.mark_prev not present, this kernel does not carry the probe", flush=True)
    sys.exit(0)

in_a, ref_a, zp_a = ref_for(model_a)
in_b, ref_b, zp_b = ref_for(model_b)
print(f"=== A={os.path.basename(model_a)}  B={os.path.basename(model_b)}  "
      f"marker 0x{MARKER:02x} ===", flush=True)

w("watch", 1)
it_a = npu(model_a)
it_b = npu(model_b)


def invoke(tag, it, indata, ref):
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    ok = md <= 2
    print(f"  {tag}: distinct={len(np.unique(got)):3d} maxdiff={md:3d}  "
          f"{'OK' if ok else 'WRONG'}", flush=True)
    return ok


a_ok = invoke("1 A                 ", it_a, in_a, ref_a)

before = len(kmsg())
w("mark_prev", MARKER)
for l in kmsg()[before:]:
    if "mark_prev:" in l:
        print(f"    {l.strip()}", flush=True)

placed = check("3 marker in place   ")
b_bad = not invoke("4 B, the walled one ", it_b, in_b, ref_b)
after_b = check("5 THE QUESTION      ")
a2_ok = invoke("6 A again           ", it_a, in_a, ref_a)
after_a = check("7 CONTROL           ")

print("", flush=True)
if not (a_ok and b_bad):
    print("  VERDICT: preconditions not met (need A ok and B wrong).", flush=True)
elif placed is None or placed < 90:
    print("  VERDICT: the marker was not in place to begin with. Probe broken.", flush=True)
elif after_a is None or after_a > 10:
    print("  VERDICT: CONTROL FAILED. A's own invoke did not clear the marker, so the",
          flush=True)
    print("           check cannot see writes. Step 5 means nothing.", flush=True)
elif after_b > 90:
    print("  VERDICT: the resident buffer is UNTOUCHED too. B's submit wrote neither its",
          flush=True)
    print("           own output nor the resident one. The no-op reading stands.",
          flush=True)
else:
    print("  VERDICT: B's submit WROTE THE RESIDENT BUFFER. It is not a no-op, it is a",
          flush=True)
    print("           re-run of the last configuration the block loaded. The question",
          flush=True)
    print("           becomes why the fetch stops after the first post-reset submit.",
          flush=True)

sys.stdout.flush()
os._exit(0)
