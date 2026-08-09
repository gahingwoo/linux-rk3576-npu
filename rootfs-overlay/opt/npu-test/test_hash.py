#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Does the walled submit write the RESIDENT job's output buffer?

Igor Paunovic's reading of the v5 results: everything measured is equally
consistent with the block never having stopped executing the resident
configuration and writing to the PREVIOUS task's addresses. That looks
identical from the failing job's own buffers, which is all round 4 looked at.

Round 5 tried to answer it by marking the resident buffer, and broke the
resident job: writing to a buffer whose ownership userspace manages through
prep_bo/fini_bo, on a device that is not dma-coherent, perturbed the thing
being measured. So this round writes nothing. rocket.hash_prev checksums the
last job's output BO in place, read-only, ownership handed back symmetrically.

  1 A(input X)  -> hash H1
  2 A(input Y)  -> hash H2    CONTROL: H2 must differ from H1, which is what
                              proves the checksum sees the block's writes. It
                              needs no perturbation, only a different input.
  3 A(input X)  -> hash H3    back to the original input, H3 should equal H1
  4 B           -> hash H4    THE QUESTION
       H4 != H3  -> the walled submit wrote A's buffer. It is a re-run of the
                    resident configuration, not a no-op, and the question
                    becomes why the fetch stops after the first post-reset
                    submit.
       H4 == H3  -> nothing wrote A's buffer either. The no-op reading holds.

Usage: TEFLON_LIB=... python3 test_hash.py <A> <B>
"""
import os
import subprocess
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model_a, model_b = sys.argv[1], sys.argv[2]
P = "/sys/module/rocket/parameters"


def ref_for(path, seed=0):
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

in_x, ref_x, zp = ref_for(model_a, 0)
in_y, ref_y, _ = ref_for(model_a, 1)
in_b, ref_b, _ = ref_for(model_b)
print(f"=== A={os.path.basename(model_a)}  B={os.path.basename(model_b)} ===", flush=True)

with open(f"{P}/watch", "w") as f:
    f.write("1\n")

it_a = npu(model_a)
it_b = npu(model_b)


def invoke(tag, it, indata, ref):
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    ok = md <= 2
    print(f"  {tag}: distinct={len(np.unique(got)):3d} maxdiff={md:3d}  "
          f"{'OK' if ok else 'WRONG'}", flush=True)
    return ok


a1 = invoke("1 A, input X        ", it_a, in_x, ref_x)
h1 = hash_prev("X1")
a2 = invoke("2 A, input Y        ", it_a, in_y, ref_y)
h2 = hash_prev("Y")
a3 = invoke("3 A, input X again  ", it_a, in_x, ref_x)
h3 = hash_prev("X2")
b_bad = not invoke("4 B, the walled one ", it_b, in_b, ref_b)
h4 = hash_prev("afterB")

print("", flush=True)
if not (a1 and a2 and a3):
    print("  VERDICT: A did not compute correctly throughout, preconditions not met.",
          flush=True)
elif not b_bad:
    print("  VERDICT: B computed. The wall was not in effect this run.", flush=True)
elif None in (h1, h2, h3, h4):
    print("  VERDICT: a checksum did not come back. Probe broken.", flush=True)
elif h1 == h2:
    print("  VERDICT: CONTROL FAILED. A different input produced the same checksum, so",
          flush=True)
    print("           the checksum does not see the block's writes. Step 4 means nothing.",
          flush=True)
elif h3 != h1:
    print("  VERDICT: the same input gave two different checksums. Something else is",
          flush=True)
    print("           writing that buffer; step 4 cannot be attributed to B.", flush=True)
elif h4 != h3:
    print("  VERDICT: B's submit CHANGED the resident buffer. It is not a no-op, it is a",
          flush=True)
    print("           re-run of the last configuration the block loaded.", flush=True)
else:
    print("  VERDICT: the resident buffer is unchanged across B. Nothing wrote it either,",
          flush=True)
    print("           so the no-op reading holds.", flush=True)

sys.stdout.flush()
os._exit(0)
