#!/usr/bin/env python3
"""
Fit the per-window OIHW *phase* law across 4 ramp multipliers {37,43,53,61}.
Run when the 4 posprobe captures come back:

    rkt2-venv/bin/python ana_phase.py dirty/npu-cap/out

Each posprobe_X holds the same-shape conv with weights = ((lin*mult)%251-125)/64.
At a fixed float-surface slot s, model m shows value v; the OIHW position it placed
there is lin_m(s) = (round(v/wt_sc)+125)*inv(m) mod 251. If the placement were purely
shape-fixed, all 4 models would agree on lin(s). They don't (a vs b differ) — so we
measure HOW lin_m(s) depends on m, per region, to see if the phase is a simple law
(=> derivable) or arbitrary (=> value-dependent blob).
"""
import sys
import numpy as np
sys.path.insert(0, "/home/parallels/Desktop/linux-rk3576-npu/vendor-capture")
import ana_posprobe as A

MULT = {"posprobe_a": 37, "posprobe_b": 53, "posprobe_c": 43, "posprobe_d": 61}


def load(root, tag):
    d = open(f"{root}/{tag}/bo01.bin", "rb").read()
    meta = open(f"{root}/{tag}/meta.txt").read()
    fs = A.fs_of(d, meta)
    u, _ = A.detect_unit(fs)
    lin, _ = A.lin_at_slots(fs, u, MULT[tag])
    return fs, u, lin


def main(root):
    data = {}
    for tag, m in MULT.items():
        try:
            fs, u, lin = load(root, tag)
            data[tag] = lin
            print(f"{tag} (*{m}): {len(lin)} weight slots, wt_sc~{u:.5f}")
        except FileNotFoundError:
            print(f"{tag}: MISSING")
    tags = [t for t in MULT if t in data]
    if len(tags) < 2:
        return
    # slots present in ALL captured models
    common = set(data[tags[0]])
    for t in tags[1:]:
        common &= set(data[t])
    common = sorted(common)
    print(f"\nslots common to all {len(tags)} models: {len(common)}")

    # per-slot: do all models agree on lin? (shape-fixed) — and if not, cluster the offsets
    base = tags[0]
    # offset of each model vs base, per slot
    offs = {t: np.array([(data[t][s] - data[base][s]) % 251 for s in common]) for t in tags[1:]}
    print(f"\n=== offset of each model vs {base} (*{MULT[base]}), per region ===")
    from collections import Counter
    for t in tags[1:]:
        c = Counter(offs[t].tolist())
        print(f"  {t} (*{MULT[t]}): top offsets {c.most_common(5)}")
    # GROUP slots by the tuple of offsets across models -> each group = a region with one phase
    sig = list(zip(*[offs[t] for t in tags[1:]]))
    grp = Counter(sig)
    print(f"\n=== regions (distinct offset-signatures): {len(grp)} ===")
    for s, n in grp.most_common(8):
        labels = ", ".join(f"{t}+{o}" for t, o in zip(tags[1:], s))
        print(f"  n={n:4d}  [{labels}]")

    # LAW TEST: within the biggest region, is lin_m(s) = C * inv(m) + K (mod 251)?  (window
    # aligned to a fixed VALUE) or = C*m + K?  Test on the window starts.
    print("\n=== phase-law fit on the dominant window (fs@9 group) ===")
    # take slots whose base lin is in the fs@9 window (lin ~ 79..325 for *37)
    win = [s for s in common if 60 <= data[base][s] <= 110]
    if win:
        s0 = win[0]
        print(f"  sample slot {s0}: " + "  ".join(f"*{MULT[t]}->lin{data[t][s0]}" for t in tags))
        for name, f in [("C*inv(m)", lambda m: pow(m, -1, 251)), ("C*m", lambda m: m)]:
            # solve C,K from two models, check the other two
            import numpy as np
            ms = [MULT[t] for t in tags]; ls = [data[t][s0] for t in tags]
            A0 = np.array([[f(ms[0]), 1], [f(ms[1]), 1]])
            try:
                CK = np.linalg.solve(A0 % 251, np.array(ls[:2]))
            except Exception:
                continue
            pred = [(round(CK[0])*f(m) + round(CK[1])) % 251 for m in ms]
            ok = sum(p == l for p, l in zip(pred, ls))
            print(f"  law lin=={name}+K : pred={pred} actual={ls}  match {ok}/{len(ms)}")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "/home/parallels/Desktop/linux-rk3576-npu/dirty/npu-cap/out"
    main(root)
