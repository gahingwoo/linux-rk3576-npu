#!/usr/bin/env python3
"""
Tomeu's isolation method, with a CORRECTNESS oracle (not a distinct-count).

Run a SINGLE-op tflite on the NPU (Teflon) and on the CPU (tflite reference)
with the SAME known input, and compare BYTE-FOR-BYTE. The verdict is maxdiff /
per-pixel error against the CPU reference -- NOT the distinct count.

WHY NOT distinct: conv2d.tflite (the synthetic test model) is quantised so its
CORRECT output saturates -- on a saturating model a correct conv and a broken
constant-fill BOTH collapse to distinct<=2, so distinct cannot tell them apart.
Use conv2d-cal.tflite (out_sc=32, out_zp=128) instead: its correct output is a
rich non-saturated map (distinct~256), so any divergence shows up in maxdiff.

Two traps this guards against:
  - distinct as a proxy: replaced by maxdiff vs the CPU reference.
  - silent CPU fallback: if teflon does NOT delegate, NPU==CPU trivially. We set
    TEFLON_DEBUG=1 so the delegate prints its partition/node count to stderr;
    read that line. maxdiff==0 only means "correct" if delegation actually ran.

Usage: TEFLON_LIB=/usr/lib/libteflon.so python3 test_conv.py <model.tflite>
"""
import os, sys
import numpy as np
import tflite_runtime.interpreter as tflite

teflon = os.environ.get("TEFLON_LIB", "/usr/lib/libteflon.so")
debug = os.environ.get("TEFLON_DEBUG", "1")   # 1 => print delegated-node count
model = sys.argv[1]


def run(use_npu, indata):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": debug})] if use_npu else []
    it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    it.allocate_tensors()
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    it.invoke()
    # Return the interpreter too: keeping it alive defers the BO teardown (the
    # kernel's drm_mm_takedown wedges the board during interpreter GC). We os._exit
    # after printing so the verdict survives the wedge.
    return it.get_tensor(out["index"])[0], inp, out, it


# Known, structured input (a byte ramp) so both backends get identical data.
det = tflite.Interpreter(model_path=model)
det.allocate_tensors()
ishape = det.get_input_details()[0]["shape"]
n = int(np.prod(ishape))
indata = (np.arange(n) % 251).astype(np.int64)

print(f"=== {os.path.basename(model)} ===", flush=True)
print("--- teflon delegate log (look for delegated node/partition count) ---", flush=True)
npu, inp, out, _it_npu = run(True, indata)   # keep _it_npu alive (defer BO teardown)
cpu, _, _, _it_cpu = run(False, indata)
print("--- end teflon log ---", flush=True)


def desc(a):
    f = a.flatten().astype(int)
    return (f"distinct={len(np.unique(f))} nonzero={np.count_nonzero(f)}/{f.size} "
            f"min={f.min()} max={f.max()} mean={f.mean():.1f} first8={f[:8].tolist()}")


print(f"  in{list(inp['shape'])} {inp['dtype'].__name__} -> out{list(out['shape'])}")
print(f"  NPU: {desc(npu)}")
print(f"  CPU: {desc(cpu)}  <- reference (the right answer)")

# Is the CPU reference itself discriminating? A saturated reference can't judge.
cf = cpu.flatten().astype(int)
cpu_distinct = len(np.unique(cf))
cpu_sat = int(((cf <= cf.min() + 0) | (cf >= 255)).sum())  # rough
if cpu_distinct <= 4:
    print(f"  WARNING: CPU reference is near-degenerate (distinct={cpu_distinct}). "
          f"This model SATURATES -- maxdiff is not discriminating. Use conv2d-cal.tflite.")

if npu.shape != cpu.shape:
    print(f"  RESULT: shape mismatch NPU{list(npu.shape)} CPU{list(cpu.shape)}")
    sys.exit(0)

d = np.abs(npu.astype(int) - cpu.astype(int))
md = int(d.max())
mad = float(d.mean())
within2 = 100.0 * (d <= 2).mean()
exact = 100.0 * (d == 0).mean()
worst = int((d > 2).sum())
print(f"  ERROR vs CPU: maxdiff={md}  mean|diff|={mad:.2f}  exact={exact:.1f}%  "
      f"within2={within2:.1f}%  pixels>2={worst}/{d.size}")

# PER-CHANNEL vs PER-PIXEL error breakdown: decide whether the requant error is a
# per-output-channel coefficient (A/bias/C -- derivable, fixable) or a per-pixel one
# (the float surface blob). Channel-variance >> spatial-variance => per-channel.
if npu.ndim == 3:
    Cc = npu.shape[2]
    flat = d.reshape(-1, Cc)
    dch = flat.mean(0)            # mean|diff| per output channel
    dpix = flat.mean(1)          # mean|diff| per spatial position
    sat = (npu.reshape(-1, Cc) >= 254).mean(0) * 100  # % saturated per channel
    print(f"  PER-CHANNEL mean|diff| ({Cc}ch): std={dch.std():.0f} "
          f"min={dch.min():.0f} max={dch.max():.0f} -> {dch.round().astype(int).tolist()}")
    print(f"  PER-CHANNEL %sat(>=254): {sat.round().astype(int).tolist()}")
    print(f"  PER-PIXEL   mean|diff| ({dpix.size}px): std={dpix.std():.0f} "
          f"min={dpix.min():.0f} max={dpix.max():.0f}")
    print(f"  channels ~right(<5): {np.where(dch < 5)[0].tolist()}")
    print(f"  channels wrong(>30): {np.where(dch > 30)[0].tolist()}")
    print(f"  VERDICT: {'PER-CHANNEL (A/bias/C coef -- DERIVABLE)' if dch.std() > 1.5*dpix.std() else 'PER-PIXEL (float surface)'}")

# Verdict on the ORACLE (maxdiff), with the delegation caveat made explicit.
if md == 0:
    print("  RESULT: maxdiff=0 -> NPU == CPU reference. CORRECT *iff* teflon "
          "actually delegated (confirm the node count in the log above; a CPU "
          "fallback would also give maxdiff=0).")
elif md <= 2:
    print(f"  RESULT: PASS -- NPU matches CPU within {md} LSB (int8 requant rounding). "
          "The conv is computing correctly.")
else:
    print(f"  RESULT: FAIL -- NPU diverges from CPU by up to {md} ({worst} pixels off "
          "by >2). The conv is genuinely wrong; this is the real bug, now localizable "
          "to actual pixels.")

# Flush the verdict, then hard-exit to skip Python/interpreter teardown -- the
# kernel wedges (drm_mm_takedown) during BO cleanup, which has been eating this
# line every run. os._exit jumps straight out, past the cleanup, with the maxdiff
# already on the wire.
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
