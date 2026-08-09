#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
CONFIG or DOMAIN? Same model, N interpreters, alternating.

Where this comes from (2026-07-26):

  test_twice.py   one interpreter, six invokes  -> all six byte-exact
  test_aba.py     two interpreters, A B A       -> the second one always fails,
                  in both directions, with two independently byte-exact models

That was read as "loading a second configuration fails". But the regcmd dump
says the configuration is not the variable: conv2d-cal's 143-entry command list
is IDENTICAL at position 1 and position 2, and conv2d vs conv2d-cal differ in
only three entries (DPU OUT_CVT offset/scale/shift at 0x40ac/0x40b0/0x40b4) --
same weights, same shapes, same buffer iovas.

What DOES differ between the two tests is something else entirely: rocket gives
each open file its own IOMMU domain, so one interpreter means one domain and
never switching, while two interpreters means a domain switch on every job. The
dumps show both models' regcmd living at the same iova (0xffef6000) backed by
different physical pages, which is exactly the situation a stale translation
would break.

So separate the two variables. Build N interpreters of the SAME model -- byte
identical configuration, by construction -- and alternate between them:

  all correct  -> domain switching is fine; the failure really is about config
                  content, and the OUT_CVT registers are where to look next
  fails from
  invoke 1 on  -> it is the DOMAIN SWITCH, not the configuration. Everything
                  said today about a "reconfiguration path" is the wrong frame,
                  and this becomes an IOMMU/TLB problem

Usage: TEFLON_LIB=... python3 test_domain.py <model> [n_interp] [n_rounds]
"""
import os
import sys

import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
model = sys.argv[1]
n_interp = int(sys.argv[2]) if len(sys.argv) > 2 else 2
n_rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 3

det = tflite.Interpreter(model_path=model)
det.allocate_tensors()
inp_d = det.get_input_details()[0]
out_d = det.get_output_details()[0]
n = int(np.prod(inp_d["shape"]))
indata = (np.arange(n) % 251).astype(np.int64)
det.set_tensor(inp_d["index"], indata.astype(inp_d["dtype"]).reshape(inp_d["shape"]))
det.invoke()
cpu = det.get_tensor(out_d["index"])[0].flatten().astype(int)
oq = out_d.get("quantization", (0.0, 0))
zp = int(oq[1]) if oq and len(oq) > 1 else 128
ref = np.maximum(cpu, zp)

print(f"=== {os.path.basename(model)}: {n_interp} interpreters x {n_rounds} rounds "
      f"(identical config, only the IOMMU domain alternates) ===", flush=True)


def npu_interp():
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": "0"})]
    it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    it.allocate_tensors()
    return it


def run(it):
    i = it.get_input_details()[0]
    o = it.get_output_details()[0]
    it.set_tensor(i["index"], indata.astype(i["dtype"]).reshape(i["shape"]))
    it.invoke()
    return it.get_tensor(o["index"])[0].flatten().astype(int)


# All interpreters built up front and kept alive, so no teardown happens between
# invokes and the only event between them is the domain switch.
its = [npu_interp() for _ in range(n_interp)]

# ONLY_FIRST=1: create every interpreter but only ever invoke the first one.
# That separates "a second IOMMU domain was created" from "a second domain was
# actually attached to the core", which are different events in rocket -- the
# attach only happens when a job runs.
only_first = os.environ.get("ONLY_FIRST") == "1"
run_set = its[:1] if only_first else its
if only_first:
    print(f"  (ONLY_FIRST: {len(its)} interpreters exist, invoking interp 0 only)",
          flush=True)

verdicts = []
for r in range(n_rounds):
    for k, it in enumerate(run_set):
        got = run(it)
        md = int(np.abs(got - ref).max())
        exact = float((got == ref).mean() * 100)
        ok = md <= 2
        verdicts.append(ok)
        print(f"  round {r} interp {k}: distinct={len(np.unique(got)):3d} "
              f"mean={got.mean():6.1f} | maxdiff={md:3d} exact={exact:5.1f}%  "
              f"{'OK' if ok else 'WRONG'}", flush=True)

if all(verdicts):
    print("  VERDICT: alternating IOMMU domains is FINE with an identical config.")
    print("           So the failure is about config CONTENT -- next stop is the")
    print("           three OUT_CVT registers that are the only difference.", flush=True)
elif verdicts[0] and not any(verdicts[1:]):
    print("  VERDICT: only the first invoke works. Config is byte-identical here, so")
    print("           this is the DOMAIN SWITCH, not the configuration. The")
    print("           'reconfiguration path' framing from today is wrong.", flush=True)
else:
    print(f"  VERDICT: mixed {verdicts} -- read the lines above.", flush=True)

sys.stdout.flush()
os._exit(0)          # skip interpreter GC; BO teardown is fragile on this kernel
