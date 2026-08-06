#!/usr/bin/env python3
"""
Does anything after the first submit of a session compute at all?

Round 6 asked something else and answered this by accident. Feeding the SAME
model a DIFFERENT input produced a byte identical output buffer: crc32 20a556ae
before and after. The block did not write it. So the second submit did not
compute, with the same configuration and only the input data changed.

That matters because every "re-running the same op is byte exact" result this
project has leaned on since June used the same input each time, and a stale
buffer is indistinguishable from a correct recomputation under that test.

This run makes the distinction directly. The checksum is of ONE latched buffer
throughout; round 6 followed each submit and ended up comparing two different
BOs.

  1 A(X)            first submit of the session   -> crc C1, must be correct
  2 A(Y)            different input, no reset     -> crc C2
       C2 == C1  the buffer was not written. Only the first submit computes.
       C2 != C1  it recomputed, and the wall is about configuration after all.
  3 sleep past autosuspend, then A(Y) again       -> crc C3
       C3 != C2  a resume, which resets, re-arms the compute. That is the
                 "one compute per reset" shape.
       C3 == C2  even a resume does not help, and the reset is not the lever.

Step 2 is its own control: if C2 differs from C1 the checksum demonstrably sees
writes, and if it does not, step 3 has to move it or the probe is blind.

Usage: TEFLON_LIB=... python3 test_once.py <model>
"""
import os
import subprocess
import sys
import time

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
P = "/sys/module/rocket/parameters"


def ref_for(path, seed):
    det = tflite.Interpreter(model_path=path)
    det.allocate_tensors()
    inp = det.get_input_details()[0]
    out = det.get_output_details()[0]
    n = int(np.prod(inp["shape"]))
    indata = ((np.arange(n) + seed * 37) % 251).astype(np.int64)
    det.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    det.invoke()
    cpu = det.get_tensor(out["index"])[0].flatten().astype(int)
    oq = out.get("quantization", (0.0, 0))
    zp = int(oq[1]) if oq and len(oq) > 1 else 128
    return indata, np.maximum(cpu, zp), zp


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


def hash_prev(tag):
    before = len(kmsg())
    with open(f"{P}/hash_prev", "w") as f:
        f.write(tag + "\n")
    for l in kmsg()[before:]:
        if "hash_prev:" in l:
            print(f"    {l.strip()}", flush=True)
            if "crc32=" in l:
                return l.split("crc32=")[1].split()[0]
    print("    (hash_prev did not fire)", flush=True)
    return None


if not os.path.exists(f"{P}/hash_prev"):
    print("  rocket.hash_prev not present, this kernel does not carry the probe", flush=True)
    sys.exit(0)

in_x, ref_x, zp = ref_for(model, 0)
in_y, ref_y, _ = ref_for(model, 1)
print(f"=== {os.path.basename(model)} (zp {zp}), one config, two inputs ===", flush=True)

with open(f"{P}/watch", "w") as f:
    f.write("1\n")
for l in kmsg()[-3:]:
    if "watch:" in l:
        print(f"    {l.strip()}", flush=True)

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
it.allocate_tensors()


def invoke(tag, indata, ref):
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    print(f"  {tag}: distinct={len(np.unique(got)):3d} maxdiff={md:3d}  "
          f"{'OK' if md <= 2 else 'WRONG'}", flush=True)
    return md <= 2


ok1 = invoke("1 A(X), first submit  ", in_x, ref_x)
c1 = hash_prev("X")

invoke("2 A(Y), no reset      ", in_y, ref_y)
c2 = hash_prev("Y")

print("  3 idling past the 50 ms autosuspend, then A(Y) again", flush=True)
time.sleep(1.0)
ok3 = invoke("  A(Y), after resume ", in_y, ref_y)
c3 = hash_prev("Yagain")

print("", flush=True)
if not ok1:
    print("  VERDICT: the first submit was already wrong, nothing to conclude.", flush=True)
elif None in (c1, c2, c3):
    print("  VERDICT: a checksum did not come back. Probe broken.", flush=True)
elif c2 != c1:
    print("  VERDICT: the second submit DID recompute on a new input. The stale buffer",
          flush=True)
    print("           reading is wrong and the wall really is about configuration.",
          flush=True)
elif c3 == c2:
    print("  VERDICT: neither a second submit nor a resume writes the buffer again. Only",
          flush=True)
    print("           the very first submit after the module loaded ever computed, and",
          flush=True)
    print("           the checksum cannot be shown to see writes at all in this run.",
          flush=True)
else:
    print("  VERDICT: a second submit does NOT compute, and a resume restores it. Every",
          flush=True)
    print("           'same op re-runs byte exact' result since June was a stale buffer:",
          flush=True)
    print(f"           one compute per reset. {'A(Y) after resume was correct.' if ok3 else 'A(Y) after resume was still wrong.'}",
          flush=True)

sys.stdout.flush()
os._exit(0)
