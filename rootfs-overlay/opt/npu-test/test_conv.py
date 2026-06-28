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


import time

def run(use_npu, indata):
    deleg = [tflite.load_delegate(teflon, options={"TEFLON_DEBUG": debug})] if use_npu else []
    it = tflite.Interpreter(model_path=model, experimental_delegates=deleg)
    it.allocate_tensors()
    inp = it.get_input_details()[0]
    out = it.get_output_details()[0]
    it.set_tensor(inp["index"], indata.astype(inp["dtype"]).reshape(inp["shape"]))
    # Time the invoke. Real NPU execution should be clearly different from the CPU
    # tflite reference; a silent CPU fallback would clock ~the same as the CPU run.
    t0 = time.perf_counter()
    it.invoke()
    dt = (time.perf_counter() - t0) * 1e3
    print(f"  [{'NPU' if use_npu else 'CPU'} invoke: {dt:.1f} ms]", flush=True)
    # Return the interpreter too: keeping it alive defers the BO teardown (the
    # kernel's drm_mm_takedown wedges the board during interpreter GC). We os._exit
    # after printing so the verdict survives the wedge.
    return it.get_tensor(out["index"])[0], inp, out, it


# Known, structured input (a byte ramp) so both backends get identical data.
det = tflite.Interpreter(model_path=model)
det.allocate_tensors()
ishape = det.get_input_details()[0]["shape"]
n = int(np.prod(ishape))
# TEST_INAMP>0 confines the input to in_zp +/- amp so the conv accumulator stays
# small (|acc| << 2^31/cvt_scale). If the NPU is byte-correct on a SMALL-acc input
# but wrong on the full ramp, the requant is overflowing the fixed-point multiply.
amp_env = os.environ.get("TEST_INAMP")
if amp_env is None:
    indata = (np.arange(n) % 251).astype(np.int64)          # default ramp
elif int(amp_env) == 0:
    indata = np.full(n, 128, dtype=np.int64)                # all in_zp -> acc = bias ONLY
else:
    amp = int(amp_env)
    indata = (128 + (np.arange(n) % (2 * amp + 1)) - amp).astype(np.int64)

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
satpct = 100.0 * ((npu == 0) | (npu >= 255)).mean()
print(f"  ERROR vs CPU: maxdiff={md}  mean|diff|={mad:.2f}  exact={exact:.1f}%  "
      f"within2={within2:.1f}%  pixels>2={worst}/{d.size}  NPU_sat(0|255)={satpct:.1f}%")

# RELU-reference: the HW appears to apply a RELU on the accumulator before requant
# (negative conv -> out_zp). For a NO-activation model that floors the negative half;
# for a model WITH ReLU (MobileNet) it is CORRECT. Compare NPU to max(CPU, out_zp):
# if this maxdiff is small while the plain maxdiff is large, the ONLY remaining error
# is the (MobileNet-correct) relu, i.e. the conv+scale is byte-correct.
try:
    out_zp_v = int(out["quantization"][1])
except Exception:
    out_zp_v = 128
relu_ref = np.maximum(cpu.astype(int), out_zp_v)
dr = np.abs(npu.astype(int) - relu_ref)
print(f"  vs RELU-ref max(CPU,{out_zp_v}): maxdiff={int(dr.max())} mean|diff|={dr.mean():.2f} "
      f"exact={100.0*(dr==0).mean():.1f}% within2={100.0*(dr<=2).mean():.1f}%")
# Characterize the residual: are the wrong pixels (vs relu-ref) the HIGH-output ones?
# (would point to a narrow BS/cvt datapath overflowing on large accumulators) or the
# relu boundary, or specific channels?
bad = dr > 2
if bad.any():
    bc = cpu.astype(int)[bad]
    nd = np.minimum(npu.astype(int), 255)[bad]
    print(f"  RELU-ref bad px (n={int(bad.sum())}): CPU[min={bc.min()} max={bc.max()} mean={bc.mean():.0f}] "
          f"frac CPU>190={100.0*(bc>190).mean():.0f}% frac CPU<128={100.0*(bc<128).mean():.0f}%  "
          f"NPU there[mean={nd.mean():.0f}]")
    if npu.ndim == 3:
        badch = bad.reshape(-1, npu.shape[2]).mean(0) * 100
        hot = np.where(badch > 20)[0]
        print(f"  bad concentrated in channels (>20% bad): n={len(hot)} {hot.tolist()[:20]}")
        # INTERIOR vs BORDER: exclude a 2-px spatial ring (padding-touching pixels). If
        # the interior is ~100% exact, the residual is purely HW-vs-tflite edge padding.
        H, W = npu.shape[0], npu.shape[1]
        if H > 6 and W > 6:
            din = dr[2:H-2, 2:W-2, :]
            nbord = int(bad.sum()) - int((din > 2).sum())
            print(f"  INTERIOR [2:{H-2},2:{W-2}]: exact={100.0*(din==0).mean():.1f}% "
                  f"within2={100.0*(din<=2).mean():.1f}% maxdiff={int(din.max())} "
                  f"| border bad={nbord}/{int(bad.sum())}")

# PER-CHANNEL vs PER-PIXEL error breakdown: decide whether the requant error is a
# per-output-channel coefficient (A/bias/C -- derivable, fixable) or a per-pixel one
# (the float surface blob). Channel-variance >> spatial-variance => per-channel.
if npu.ndim == 3:
    Cc = npu.shape[2]
    flat = d.reshape(-1, Cc)
    dch = flat.mean(0)            # mean|diff| per output channel
    dpix = flat.mean(1)          # mean|diff| per spatial position
    sat = (npu.reshape(-1, Cc) >= 254).mean(0) * 100  # % saturated per channel
    # raw per-channel NPU value at pixel(0,0): for a CONSTANT input this is the whole
    # output (spatially uniform), so it maps acc=bias -> NPU value directly per channel.
    print(f"  NPU[px0] per-ch: {npu.reshape(-1, Cc)[0].astype(int).tolist()}")
    print(f"  CPU[px0] per-ch: {cpu.reshape(-1, Cc)[0].astype(int).tolist()}")
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
