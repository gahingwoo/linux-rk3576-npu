#!/usr/bin/env python3
"""
Decide the coef float-surface WEIGHT PLACEMENT from the two matched-shape probes
(build_posprobe.py). Run the instant the board files come back:

    rkt2-venv/bin/python ana_posprobe.py            # reads dirty/posprobe_{a,b}/bo01.bin
    rkt2-venv/bin/python ana_posprobe.py DIR_A DIR_B

posprobe_a weights = OIHW ramp  w[lin] = ((lin*37)%251 - 125)/64  (lin = OIHW index,
oc*IC*KH*KW + ic*KH*KW + ky*KW + kx). After per-tensor quant the float-surface weight
slots are wt_sc*(wq-wt_zp) ~ wt_sc*((lin*37)%251-125). Two facts make placement readable:
  - consecutive OIHW lin -> the integer steps by +37 (mod 251). So a run of float-surface
    slots whose integers step +37 mod 251 IS a contiguous OIHW window, and its start lin
    decodes by inverting (lin*37)%251.
  - posprobe_b (different weights, same shape): if its weight-slot mask == a's, placement
    is POSITION-FIXED (derivable). If it differs, value-dependent (blob).
"""
import sys, struct, re
import numpy as np

OC, IC, KH, KW = 128, 16, 5, 5
N = OC*IC*KH*KW
INV37 = pow(37, -1, 251)


def fs_of(d, meta):
    dma = int(re.search(r"idx=1 handle=\d+ dma=0x([0-9a-f]+)", meta).group(1), 16)
    h = next(i for i in range(len(d)-10) if d[i] == 0x20 and d[i+1] == 0x50 and d[i+8] == 0x24 and d[i+9] == 0x50)
    v24 = (((struct.unpack_from('<I', d, h+12)[0] & 0xffff) << 16) | (struct.unpack_from('<I', d, h+8)[0] >> 16)) & 0xffffffff
    off = (v24 - dma) & 0xffffffff
    raw = np.frombuffer(d[off:h//4*4], dtype='<f4').copy()
    raw[~np.isfinite(raw)] = 0; raw[np.abs(raw) > 1e5] = 0
    return raw


def detect_unit(fs):
    """wt_sc: the base unit making the most |value|<2.2 slots integer multiples."""
    cand = np.abs(fs[(np.abs(fs) > 0.01) & (np.abs(fs) < 2.4)])
    if len(cand) == 0: return None
    best = None
    for u in np.linspace(cand.min(), cand.min()*4, 400):
        if u < 1e-4: continue
        frac = np.mean(np.abs(cand/u - np.round(cand/u)) < 0.06)
        if best is None or frac > best[1]: best = (u, frac)
    return best


def weight_slots(fs, unit):
    r = fs/unit
    ri = np.round(r).astype(int)
    m = (np.abs(r-ri) < 0.08) & (fs != 0) & (np.abs(ri) <= 127)
    # drop long constant runs (skeleton blocks like in_sc / structural)
    idx = np.where(m)[0]
    return idx, ri


def decode_windows(fs, unit):
    idx, ri = weight_slots(fs, unit)
    wins = []; cur = [idx[0]] if len(idx) else []; hiccup = 0
    for k in range(1, len(idx)):
        a, b = idx[k-1], idx[k]
        # contiguous in slot AND integer steps +37 mod 251 (with +74/+0 tolerance for a
        # single mis-rounded slot, i.e. 2*37 or 0 mod 251 spanning one bad slot)
        contig = idx[k] == idx[k-1]+1
        d = (ri[b]-ri[a]) % 251
        if contig and d == 37:
            cur.append(b); hiccup = 0
        elif contig and d in (74, 0) and hiccup == 0:
            cur.append(b); hiccup = 1          # tolerate one mis-rounded slot, keep going
        else:
            if len(cur) >= 4: wins.append(cur)
            cur = [b]; hiccup = 0
    if len(cur) >= 4: wins.append(cur)
    out = []
    for w in wins:
        i0 = ri[w[0]]
        lin0 = (((i0 + 125) % 251) * INV37) % 251     # lin mod 251 at window start
        out.append((w[0], len(w), int(lin0)))
    # stitch fragments whose OIHW lin continues (frag2 starts where frag1 ends, mod 251)
    out.sort()
    merged = []
    for fso, L, lin0 in out:
        if merged:
            pf, pL, pl0 = merged[-1]
            gap = fso - (pf + pL)                       # 0..2 slots dropped at the break
            if 0 <= gap <= 2 and abs(((pl0 + pL + gap) - lin0) % 251) <= 1:
                merged[-1] = (pf, (fso - pf) + L, pl0); continue
        merged.append((fso, L, lin0))
    return merged, idx


def main(da, db):
    fa = fs_of(open(f"{da}/bo01.bin", "rb").read(), open(f"{da}/meta.txt").read())
    ua, fra = detect_unit(fa)
    print(f"posprobe_a: {len(fa)} f32, {np.sum(fa!=0)} nz, wt_sc~{ua:.5f} ({fra*100:.0f}% int)")
    wins, idx_a = decode_windows(fa, ua)
    print(f"  weight slots: {len(idx_a)}   contiguous OIHW windows (+37 mod251): {len(wins)}")
    cover = set()
    for fso, L, lin0 in sorted(wins):
        print(f"   fs@{fso:5d} len={L:4d}  OIHW lin0(mod251)={int(lin0):3d}")
        cover |= set(range(L))
    print(f"  VERDICT-A: {'WINDOWS DECODE -> placement is OIHW-contiguous = DERIVABLE' if len(wins)>=3 else 'no coherent windows'}")
    try:
        fb = fs_of(open(f"{db}/bo01.bin", "rb").read(), open(f"{db}/meta.txt").read())
        ub, _ = detect_unit(fb)
        idx_b, _ = weight_slots(fb, ub)
        sa, sb = set(idx_a.tolist()), set(idx_b.tolist())
        jac = len(sa & sb)/max(1, len(sa | sb))
        print(f"\nposprobe_b weight slots: {len(idx_b)}")
        print(f"weight-slot mask Jaccard a-vs-b: {jac:.3f}  "
              f"-> {'POSITION-FIXED (derivable)' if jac > 0.85 else 'VALUE-DEPENDENT (blob)' if jac < 0.6 else 'PARTIAL — inspect'}")
    except FileNotFoundError:
        print("\n(posprobe_b not present; A-verdict stands)")


if __name__ == "__main__":
    R = "/home/parallels/Desktop/linux-rk3576-npu"
    a = sys.argv[1] if len(sys.argv) > 1 else f"{R}/dirty/posprobe_a"
    b = sys.argv[2] if len(sys.argv) > 2 else f"{R}/dirty/posprobe_b"
    main(a, b)
