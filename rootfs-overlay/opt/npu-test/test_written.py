#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Is the walled submit's output buffer written at all?

Round 3 tried to answer "does B read its regcmd" by comparing B's output with
and without a corrupted regcmd. That was void: B writes out a flat zero point
surface either way, and two constant buffers always compare identical. The
oracle returned the same answer for both of its hypotheses.

This one can tell them apart. rocket.prefill=0xa5 fills the output BOs with a
marker just before OP_EN. teflon copies the output BO out with a +0x80 applied,
so the marker shows up in the tensor as 0x25 (37) and cannot be confused with
the zero point fill:

  output is 37    -> nothing wrote the buffer, the submit did nothing at all
  output is zp    -> the block DID write it, so it knew the output address, and
                     the address can only have come from a configuration it read

Modes, run as separate processes:

  control   prefill the FIRST submit of the session, which computes correctly.
            The marker MUST be gone and the result correct. If 37 survives here
            the block never writes anything and the test says nothing.

  test      run A so it is resident, then prefill B's submit, the one that
            never lands.

Usage: TEFLON_LIB=... python3 test_written.py <A> {control|test} [B]
"""
import os
import subprocess
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
mode = sys.argv[2]
model_b = sys.argv[3] if len(sys.argv) > 3 else None
PARAM = "/sys/module/rocket/parameters/prefill"
MARKER_BO = 0xA5
MARKER_OUT = (MARKER_BO + 0x80) & 0xFF          # what teflon turns it into


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


def arm():
    with open(PARAM, "w") as f:
        f.write(str(MARKER_BO) + "\n")


def show(before):
    lines = [l for l in kmsg()[len(before):] if "prefill:" in l]
    for l in lines:
        print(f"    {l.strip()}", flush=True)
    return bool(lines)


def verdict(got, ref, tag):
    marked = int((got == MARKER_OUT).sum())
    frac = marked / got.size * 100
    md = int(np.abs(got - ref).max())
    print(f"    {tag}: distinct={len(np.unique(got)):3d} mean={got.mean():6.1f} "
          f"maxdiff={md:3d}  marker({MARKER_OUT}) survives in {frac:5.1f}% of bytes",
          flush=True)
    return frac


indata, ref, zp = ref_for(model)
print(f"=== {os.path.basename(model)} (zp {zp})  mode={mode}  "
      f"marker 0x{MARKER_BO:02x} -> {MARKER_OUT} ===", flush=True)

if not os.path.exists(PARAM):
    print("  rocket.prefill not present, this kernel does not carry the probe", flush=True)
    sys.exit(0)

it = npu(model)

if mode == "control":
    before = kmsg()
    arm()
    got = run(it, indata)
    fired = show(before)
    frac = verdict(got, ref, "A, first submit, output prefilled")
    print("", flush=True)
    if not fired:
        print("  VERDICT: the prefill did not fire. Probe broken.", flush=True)
    elif frac > 50:
        print("  VERDICT: CONTROL FAILED. The marker survived a submit that computes,",
              flush=True)
        print("           so the prefill is not landing in the buffer teflon reads back.",
              flush=True)
        print("           Nothing else in this run means anything.", flush=True)
    else:
        print("  VERDICT: control good. A computing submit overwrites the marker, so a",
              flush=True)
        print("           surviving marker really does mean nothing was written.", flush=True)
else:
    it_b = npu(model_b)
    in_b, ref_b, zp_b = ref_for(model_b)

    got_a = run(it, indata)
    a_ok = int(np.abs(got_a - ref).max()) <= 2
    print(f"  1 A, makes A resident: {'OK' if a_ok else 'WRONG'}", flush=True)

    print("  2 B, first submit, output buffers PREFILLED", flush=True)
    before = kmsg()
    arm()
    got_b = run(it_b, in_b)
    fired = show(before)
    frac = verdict(got_b, ref_b, "B")
    print("", flush=True)
    if not a_ok:
        print("  VERDICT: A was not ok, preconditions not met.", flush=True)
    elif not fired:
        print("  VERDICT: the prefill did not fire. Probe broken.", flush=True)
    elif frac > 50:
        print("  VERDICT: the marker SURVIVED. B's output buffer was never written, so",
              flush=True)
        print("           the walled submit does nothing at all: it does not even know",
              flush=True)
        print("           where to write. Nothing of B's configuration was loaded.",
              flush=True)
    else:
        print("  VERDICT: the marker is GONE, so the block DID write B's output buffer",
              flush=True)
        print("           and therefore knew B's output address. B's configuration was",
              flush=True)
        print("           read; the wall is in what happens after the load.", flush=True)

sys.stdout.flush()
os._exit(0)
