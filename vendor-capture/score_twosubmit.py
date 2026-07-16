#!/usr/bin/env python3
"""
Score the VENDOR two-submit control. Pull exp_run0..4.bin + exp_b0/b1.bin off
the SD (/opt/npu-cap/) into a dir and run:  python3 score_twosubmit.py <dir>

Oracle (respects metric discipline -- no distinct-count as the correctness call):
  - run0 vs simulator golden (exp2_golden.npy): layout-robust sorted maxdiff.
    Small => run0 is the REAL conv (positive control that the rig computes).
  - runN vs run0: exact byte/float identity. This is the decisive test.
      all equal            => vendor RE-ARMS per submit within one power session
                              => rocket's gap is timing/order, NOT a register.
      run1.. CONSTANT      => vendor ALSO walls on submit>=2 (empty MAC pinned to
                              output zero-point) => the wall is NORMAL hw
                              behaviour; per-op dispatch is a dead end, chain it.
"""
import sys, os, numpy as np

d = sys.argv[1] if len(sys.argv) > 1 else "."
gpath = os.path.join(os.path.dirname(__file__), "exp2_golden.npy")
golden = np.load(gpath).astype(np.float32).ravel() if os.path.exists(gpath) else None


def load(name):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return None
    return np.fromfile(p, dtype=np.float32)


def stat(a):
    return f"n={a.size} distinct={len(np.unique(a))} min={a.min():.5g} max={a.max():.5g} " \
           f"{'CONSTANT(empty-MAC)' if a.min() == a.max() else 'RICH(real-MAC)'}"


run0 = load("exp_run0.bin")
if run0 is None:
    print("no exp_run0.bin in", d); sys.exit(1)

print("== positive control: run0 vs simulator golden ==")
if golden is not None and golden.size == run0.size:
    md = np.abs(np.sort(golden) - np.sort(run0)).max()
    rng = golden.max() - golden.min()
    print(f"  sorted maxdiff = {md:.5g}  (golden range {rng:.5g}, {100*md/max(rng,1e-9):.2f}% of range)")
    print(f"  => run0 is {'the REAL conv' if md < 0.02*max(rng,1e-9) else 'NOT matching golden -- investigate'}")
else:
    print("  (golden missing or size mismatch; skipping)")
print("  run0:", stat(run0))

print("\n== decisive: runN vs run0 (Regime A, one ctx x5) ==")
for i in range(1, 5):
    a = load(f"exp_run{i}.bin")
    if a is None:
        continue
    ident = a.size == run0.size and np.array_equal(a, run0)
    print(f"  run{i}: {stat(a)}  | identical_to_run0={ident}")

print("\n== power-cycle control (Regime B): post-4s-idle fresh submit ==")
pc = load("exp_pc.bin")
if pc is not None:
    ident = pc.size == run0.size and np.array_equal(pc, run0)
    print(f"  pc: {stat(pc)}  | identical_to_run0={ident}  (RICH here confirms the model is fine + session boundary re-arms)")

print("\n== VERDICT ==")
runs = [load(f"exp_run{i}.bin") for i in range(5)]
runs = [r for r in runs if r is not None]
later = runs[1:]
if later and all(np.array_equal(r, run0) for r in later):
    print("  vendor RE-ARMS per submit -> rocket gap = timing/ordering, wall is NOT normal.")
elif later and all(r.min() == r.max() for r in later):
    print("  vendor ALSO walls on submit>=2 -> the wall is NORMAL hw behaviour. CHAIN, don't spread.")
else:
    print("  MIXED/partial -- inspect the per-run lines above.")
