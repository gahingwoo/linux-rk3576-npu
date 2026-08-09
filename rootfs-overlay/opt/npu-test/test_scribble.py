#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Does the block re-read the regcmd buffer, or run from resident state?

Round 1 (test_probe.py) pointed PC_BASE_ADDRESS at an unmapped iova and got no
IOMMU fault on either the walled submit or the working one, and the poisoned job
still computed byte exact. That rules out "it executed from the poison", but it
cannot tell whether the real buffer was re-read, and it depends on the IOMMU
reporting a fault it may not report.

So corrupt the bytes instead of the pointer. rocket.scribble=N writes 0xdeadbeef
over the first N words of the regcmd, in place, just before OP_EN, and logs the
first word before and after so a write that did not land is visible as such.

  result still byte exact -> the block did NOT re-read the buffer
  result wrong            -> it did

Two modes, run as two separate processes so the NPU suspends in between and the
control really is a first load:

  control   arm the scribble BEFORE the first invoke of the session. Nothing can
            be resident yet, so this submit HAS to read the buffer. It must come
            back WRONG. If it does not, the scribble is landing somewhere the
            block never looks and the question run means nothing.

  question  invoke once so the config is resident and known good, then arm the
            scribble and invoke again.

  wall-ref  \\  aim the same probe at the wall itself. Run A so it is resident,
  wall-test /   then run B, which is the configuration that never lands. wall-ref
                runs B with a clean regcmd and saves its output; wall-test runs B
                with the regcmd scribbled and compares byte for byte.

                  identical -> B's regcmd was never read, and the wall IS "the
                               incoming configuration is never loaded"
                  different -> B did read it, so the wall is downstream of the
                               fetch

Usage: TEFLON_LIB=... python3 test_scribble.py <model> {control|question} [words]
       TEFLON_LIB=... python3 test_scribble.py <A> {wall-ref|wall-test} <B> [words]
"""
import os
import subprocess
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
mode = sys.argv[2]
if mode.startswith("wall"):
    model_b = sys.argv[3]
    words = sys.argv[4] if len(sys.argv) > 4 else "64"
else:
    words = sys.argv[3] if len(sys.argv) > 3 else "64"
PARAM = "/sys/module/rocket/parameters/scribble"
WALLREF = "/tmp/wall-ref.npy"


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
        f.write(words + "\n")


def show(before):
    lines = [l for l in kmsg()[len(before):] if "scribble:" in l]
    for l in lines:
        print(f"    {l.strip()}", flush=True)
    if not lines:
        print("    (the scribble did not fire)", flush=True)
        return False
    # "first AAAAAAAA -> BBBBBBBB": the write landed only if B is the poison
    return any("-> deadbeef" in l for l in lines)


indata, ref, zp = ref_for(model)
print(f"=== {os.path.basename(model)} (zp {zp})  mode={mode}  words={words} ===", flush=True)

if not os.path.exists(PARAM):
    print("  rocket.scribble not present, this kernel does not carry the probe", flush=True)
    sys.exit(0)

deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
it.allocate_tensors()


def step(tag):
    got = run(it, indata)
    md = int(np.abs(got - ref).max())
    ok = md <= 2
    print(f"  {tag}: distinct={len(np.unique(got)):3d} maxdiff={md:3d}  "
          f"{'OK' if ok else 'WRONG'}", flush=True)
    return ok


if mode == "control":
    print("  arming BEFORE the first invoke of this session", flush=True)
    before = kmsg()
    arm()
    ok = step("first submit, scribbled")
    landed = show(before)
    print("", flush=True)
    if not landed:
        print("  VERDICT: the scribble never reached the buffer (no deadbeef readback).",
              flush=True)
        print("           The probe is broken, not the hypothesis.", flush=True)
    elif ok:
        print("  VERDICT: CONTROL FAILED. A first submit, which cannot have anything",
              flush=True)
        print("           resident, computed byte exact from a corrupted regcmd. The",
              flush=True)
        print("           scribble is landing somewhere the block does not read.",
              flush=True)
    else:
        print("  VERDICT: control good. A submit that must read the buffer does read it,",
              flush=True)
        print("           so the question run can be believed.", flush=True)
elif mode.startswith("wall"):
    deleg_b = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    it_b = tflite.Interpreter(model_path=model_b, experimental_delegates=deleg_b)
    it_b.allocate_tensors()
    in_b, ref_b, zp_b = ref_for(model_b)

    a_ok = step("1 A, makes A resident")

    scribbled = mode == "wall-test"
    before = kmsg()
    if scribbled:
        print("  2 B, first submit, regcmd SCRIBBLED", flush=True)
        arm()
    else:
        print("  2 B, first submit, regcmd clean (reference)", flush=True)

    got_b = run(it_b, in_b)
    md = int(np.abs(got_b - ref_b).max())
    print(f"    B: distinct={len(np.unique(got_b)):3d} mean={got_b.mean():6.1f} "
          f"maxdiff={md:3d}  {'OK' if md <= 2 else 'WRONG'}", flush=True)
    landed = show(before) if scribbled else True

    if not a_ok:
        print("  VERDICT: A was not ok, preconditions not met.", flush=True)
    elif not scribbled:
        np.save(WALLREF, got_b)
        print(f"  saved B's clean output to {WALLREF}", flush=True)
        print("  VERDICT: reference captured, now run wall-test.", flush=True)
    elif not landed:
        print("  VERDICT: the scribble never reached the buffer. Probe broken.", flush=True)
    elif not os.path.exists(WALLREF):
        print("  VERDICT: no reference saved, run wall-ref first.", flush=True)
    else:
        ref_out = np.load(WALLREF)
        same = ref_out.shape == got_b.shape and bool((ref_out == got_b).all())
        diff = 0 if same else int((ref_out != got_b).sum())
        print(f"    vs clean-B reference: {'IDENTICAL' if same else f'{diff} bytes differ'}",
              flush=True)
        print("", flush=True)
        if same:
            print("  VERDICT: B produced the SAME bytes with its regcmd destroyed as with",
                  flush=True)
            print("           it intact. The incoming configuration is never read. The wall",
                  flush=True)
            print("           is the load, not anything downstream of it.", flush=True)
        else:
            print("  VERDICT: destroying B's regcmd changed B's output, so B DID read it.",
                  flush=True)
            print("           The wall is downstream of the fetch.", flush=True)

else:
    base_ok = step("1 baseline, clean  ")
    print("  2 same config, scribbled", flush=True)
    before = kmsg()
    arm()
    ok = step("    repeat            ")
    landed = show(before)
    print("", flush=True)
    if not base_ok:
        print("  VERDICT: the baseline was already wrong, nothing to conclude.", flush=True)
    elif not landed:
        print("  VERDICT: the scribble never reached the buffer. Probe broken.", flush=True)
    elif ok:
        print("  VERDICT: a repeat submit computes byte exact from a regcmd full of",
              flush=True)
        print("           0xdeadbeef. The block does NOT re-read the buffer, it runs from",
              flush=True)
        print("           resident state. Read this together with the control run.",
              flush=True)
    else:
        print("  VERDICT: the repeat submit DID re-read the buffer. Not resident state,",
              flush=True)
        print("           so the wall is downstream of the fetch.", flush=True)

sys.stdout.flush()
os._exit(0)
