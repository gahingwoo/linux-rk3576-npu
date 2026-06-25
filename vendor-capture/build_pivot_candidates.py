#!/usr/bin/env python3
"""
Build the two coefficient-buffer candidates that test THE pivot question:
is the vendor's value-dependent weight-surface placement load-bearing, or just an
optimization a derivable encoder can ignore?

Both start from the vendor's known-good `vendor-bias.bin` (ABC 1024 + float surface
19776) which COMPUTES (distinct=256), and touch ONLY the weight-scatter slots:

  H-shufW.bin        weight slots shuffled among themselves (same multiset, skeleton/
                     ABC byte-identical). maxdiff small => value-to-slot assignment does
                     NOT matter -> derive the mask, fill any order -> DERIVABLE.
                     maxdiff large => the exact placement is load-bearing (blob).
  plain-oihw-bias.bin  weight slots refilled with dequant weights in plain OIHW order
                     (a specific derivable layout). NB caveat: the surface holds only
                     ~2427 weight slots vs 51200 conv weights, so this fills the first
                     2427 OIHW weights -- a *guess* at the reduction, judged by the oracle.

Run via the S97mesarepro harness with ROCKET_BIAS_FILE; judge by test_conv.py maxdiff.
"""
import numpy as np

R = "/home/parallels/Desktop/linux-rk3576-npu"
OC, KH, KW, IC = 128, 5, 5, 16
WT_SC, WT_ZP = 3.9125464, 133


def weight_slots(fs):
    r = fs / WT_SC
    ri = np.round(r)
    return np.where((np.abs(r - ri) < 0.03) & (fs != 0) & (np.abs(ri) <= 127) & (np.abs(fs) < 200))[0]


def main():
    raw = bytearray(open(f"{R}/dirty/npu-test/vendor-bias.bin", "rb").read())
    abc = bytes(raw[:1024])
    fs = np.frombuffer(bytes(raw[1024:1024 + 4944 * 4]), dtype='<f4').copy()
    clean = fs.copy(); clean[~np.isfinite(clean)] = 0; clean[np.abs(clean) > 1e5] = 0
    ws = weight_slots(clean)

    def save(name, out):
        b = bytearray(abc) + bytearray(out.tobytes())
        b = b[:20800] + bytes(max(0, 20800 - len(b)))
        open(f"{R}/dirty/npu-test/{name}", "wb").write(b)
        print(f"wrote {name}: touched {np.sum(fs.view('<u4') != out.view('<u4'))} slots (all weight slots)")

    # H-shufW: permute only the weight-slot values
    out = fs.copy()
    out[ws] = fs[ws][np.random.RandomState(0).permutation(len(ws))]
    save("H-shufW.bin", out)

    # plain-oihw: weight slots in plain OIHW order
    wqu = np.frombuffer(open(f"{R}/vendor-capture/conv2d_weights.i8", "rb").read(),
                        dtype=np.uint8).astype(int).reshape(OC, KH, KW, IC)
    oihw = (np.transpose(wqu - WT_ZP, (0, 3, 1, 2)).reshape(-1).astype(np.float32)) * WT_SC
    out = fs.copy()
    for k, s in enumerate(ws):
        out[s] = oihw[k % len(oihw)]
    save("plain-oihw-bias.bin", out)


if __name__ == "__main__":
    main()
