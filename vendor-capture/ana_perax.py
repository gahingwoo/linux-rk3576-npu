#!/usr/bin/env python3
"""
Decode + judge a captured SDP coefficient buffer (from the per-axis capture image,
CAPTURE-PERAX.md). Run the instant the board log comes back:

    rkt2-venv/bin/python ana_perax.py <coef.bin>            # a *-coef.bin (tail) or full bo01
    rkt2-venv/bin/python ana_perax.py --b64 boot_log.txt    # extract the BEGIN/END b64 blocks

THE DECISIVE QUESTION it answers: does the **per-axis** float surface decode to the
dequantised weights (derivable -> the encoder is writable), while the **per-tensor**
one stays a blob? It parses ABC, checks the derivable A term, and tries to line the
float surface up against conv2d's float weights (c2d_perax = conv2d weights, per-axis).

Validated on the per-tensor vendor-bias.bin (expect: A correlates, float surface does
NOT decode to a clean weight layout = blob).
"""
import sys, base64, re
import numpy as np

R = "/home/parallels/Desktop/linux-rk3576-npu"
OC, KH, KW, IC = 128, 5, 5, 16
IN_SC, WT_SC, OUT_SC = 0.0078125, 3.9125464, 0.0235
IN_ZP, WT_ZP = 128, 133
M = IN_SC * WT_SC / OUT_SC


def weights_float():
    """conv2d's original float weights (OHWI), the floats c2d_perax was built from."""
    wq = np.frombuffer(open(R + "/vendor-capture/conv2d_weights.i8", "rb").read(),
                       dtype=np.uint8).astype(int).reshape(OC, KH, KW, IC)
    return (wq - WT_ZP).astype(np.float32) * WT_SC   # (oc,ky,kx,ic) float


def parse(buf):
    if len(buf) > 30000:            # full bo01 -> coef tail is [51200:]
        buf = buf[51200:]
    A = np.array([int.from_bytes(buf[(o // 8) * 64 + (o % 8) * 4:(o // 8) * 64 + (o % 8) * 4 + 4], 'little', signed=True) for o in range(OC)])
    g = lambda base, o: int.from_bytes(buf[(o // 8) * 64 + base + (o % 8) * 2:(o // 8) * 64 + base + (o % 8) * 2 + 2], 'little', signed=True)
    B = np.array([g(32, o) for o in range(OC)])
    C = np.array([g(48, o) for o in range(OC)])
    fs = np.frombuffer(buf[1024:1024 + (len(buf) - 1024) // 4 * 4], dtype='<f4').copy()
    fs[~np.isfinite(fs)] = 0
    return A, B, C, fs


def judge(buf, label):
    A, B, C, fs = parse(buf)
    print(f"\n===== {label} (coef {len(buf if len(buf)<=30000 else buf[51200:])}B) =====")
    print(f"ABC: A[:4]={A[:4].tolist()} B[:4]={B[:4].tolist()} C[:4]={C[:4].tolist()}  "
          f"C distinct={len(set(C.tolist()))} (1=per-tensor, many=per-channel)")
    # derivable A term
    wq = np.frombuffer(open(R + "/vendor-capture/conv2d_weights.i8", "rb").read(), dtype=np.uint8).astype(int).reshape(OC, KH, KW, IC)
    sw = (wq - WT_ZP).reshape(OC, -1).sum(1)
    try:
        bias = np.frombuffer(open(R + "/vendor-capture/conv2d_bias.i32", "rb").read(), dtype=np.int32)
        print(f"A vs -(bias-in_zp*sw): corr={np.corrcoef(A, -(bias - IN_ZP*sw))[0,1]:.4f}")
    except FileNotFoundError:
        pass
    # float surface vs the dequant weights, in candidate per-axis orders
    wf = weights_float()
    nz = fs[np.abs(fs) > 1e-6]
    print(f"float surface: {len(fs)} f32, {len(nz)} nonzero, {len(set(np.round(nz,3).tolist()))} distinct")
    orders = {
        "OHWI  oc,ky,kx,ic": wf,
        "oc,ic,ky,kx":       np.transpose(wf, (0, 3, 1, 2)),
        "oc,ky,kx,ic flat":  wf,
    }
    best = None
    for name, arr in orders.items():
        seq = arr.reshape(-1)
        # align the float-surface nonzeros against this weight order (skip pad zeros in fs)
        fnz = fs[fs != 0]
        n = min(len(fnz), len(seq))
        if n < 16:
            continue
        # value-multiset overlap (cheap derivability signal)
        from collections import Counter
        ca, cb = Counter(np.round(fnz, 3).tolist()), Counter(np.round(seq[seq != 0], 3).tolist())
        inter = sum((ca & cb).values())
        frac = inter / max(1, sum(ca.values()))
        if best is None or frac > best[1]:
            best = (name, frac)
    if best:
        print(f"float-surface value-overlap with dequant weights: best order '{best[0]}' = {best[1]*100:.1f}%")
    # decisive verdict
    derivable = best and best[1] > 0.9
    print(f"VERDICT: {'PER-AXIS DERIVABLE (float surface == dequant weights)' if derivable else 'BLOB / not a clean weight decode (per-tensor-like)'}")
    return derivable


def from_log(path):
    txt = open(path, errors="ignore").read()
    out = {}
    for tag in ("perax", "pertensor"):
        m = re.search(rf"-----BEGIN {tag} COEF B64-----\s*(.*?)\s*-----END {tag} COEF B64-----", txt, re.S)
        if m:
            out[tag] = base64.b64decode("".join(m.group(1).split()))
            print(f"extracted {tag}: {len(out[tag])} bytes from log")
        else:
            print(f"NO {tag} block found in log")
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--b64":
        bufs = from_log(sys.argv[2])
        for tag, buf in bufs.items():
            judge(buf, tag)
    elif len(sys.argv) >= 2:
        judge(open(sys.argv[1], "rb").read(), sys.argv[1].split("/")[-1])
    else:
        # self-test on the per-tensor ground truth
        judge(open(R + "/dirty/npu-test/vendor-bias.bin", "rb").read(), "vendor-bias.bin (per-tensor self-test)")
