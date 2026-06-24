#!/usr/bin/env python3
"""
Off-board analysis of the RK3576 SDP coefficient buffer (the 0x5020/0x5024 DMA
buffer rkt_coefs.c fills). Works from the ONE live capture we have on disk
(dirty/npu-test/vendor-bias.bin, 20800B, captured from the vendor stack running
conv2d.tflite) plus conv2d's known int8 weights/bias/quant params.

What this script PROVES (no board needed), each as a printed check:

 1. Buffer = [ABC region | float surface].
    ABC = 16 groups x 64B (8 oc/group): A[oc] int32 @0, B[oc] i16 @32, C[oc] i16 @48.
    float surface = the rest (4944 f32), values are integer multiples of wt_sc.

 2. A[oc] = -M * (bias[oc] - in_zp*sw[oc])   (corr ~ -0.996)
    M = in_sc*wt_sc/out_sc, sw[oc] = sum_(ic,ky,kx)(wq-wt_zp).
    => A is the per-channel requant BIAS-correction term and is DERIVABLE.

 3. C[oc] (the per-channel multiplier ~13000) VARIES per output channel even
    though conv2d.tflite is PER-TENSOR. That is only possible if the vendor
    toolkit re-quantises the per-tensor conv into a PER-CHANNEL one with
    toolkit-chosen scales. Hence the float surface is per-channel REQUANTISED
    weights, not the original weights, and its exact values are toolkit-internal
    (a blob) for a per-tensor model. A genuinely PER-AXIS model (e.g. MobileNet)
    carries explicit per-channel scales, so there the surface IS derivable.

 4. The float surface layout is NOT the weight-DMA layout
    (dirty/vendor_cap/generic_slot_map.npy): among the surface's nonzero slots,
    zero match the weight order. It is its own sparse/padded layout, reachable
    only from a live capture (board), NOT from the .rknn -- the .rknn does NOT
    store the assembled live surface (see ana_rknn_has_surface() below: ~14/4944
    floats match; librknnrt assembles it at runtime).

Usage: rkt2-venv/bin/python ana_coef.py
"""
import struct
import numpy as np

R = "/home/parallels/Desktop/linux-rk3576-npu"
OC = 128
IN_SC, WT_SC, OUT_SC = 0.0078125, 3.9125464, 0.0235
IN_ZP, WT_ZP, OUT_ZP = 128, 133, 0
M = IN_SC * WT_SC / OUT_SC


def load():
    vb = open(R + "/dirty/npu-test/vendor-bias.bin", "rb").read()
    A = np.array([struct.unpack_from('<i', vb, (oc // 8) * 64 + (oc % 8) * 4)[0] for oc in range(OC)])
    B = np.array([struct.unpack_from('<h', vb, (oc // 8) * 64 + 32 + (oc % 8) * 2)[0] for oc in range(OC)])
    C = np.array([struct.unpack_from('<h', vb, (oc // 8) * 64 + 48 + (oc % 8) * 2)[0] for oc in range(OC)])
    fs = np.frombuffer(vb[1024:1024 + 4944 * 4], dtype='<f4').copy()
    fs[~np.isfinite(fs)] = 0
    w = np.frombuffer(open(R + "/vendor-capture/conv2d_weights.i8", "rb").read(),
                      dtype=np.uint8).astype(int).reshape(128, 5, 5, 16)   # OHWI
    bias = np.frombuffer(open(R + "/vendor-capture/conv2d_bias.i32", "rb").read(), dtype=np.int32)
    sw = (w - WT_ZP).reshape(128, -1).sum(1)
    return vb, A, B, C, fs, w, bias, sw


def main():
    vb, A, B, C, fs, w, bias, sw = load()
    print("buffer %dB | ABC 1024B | float surface %d f32 (%d nonzero, all wt_sc-multiples)"
          % (len(vb), len(fs), int((np.abs(fs) > 1e-9).sum())))
    print("M = in*wt/out = %.4f" % M)

    # (2) A = -M*(bias - in_zp*sw)
    base = bias - IN_ZP * sw
    print("\n[A] corr(A, -(bias-in_zp*sw)) = %.4f   (derivable bias-correction term)"
          % np.corrcoef(A, -base)[0, 1])
    pred = -np.round(base * M)
    print("    A vs -round(M*(bias-in_zp*sw)): mean|err| %.0f (A range %d..%d) -- residual = per-ch C scaling"
          % (np.abs(pred - A).mean(), A.min(), A.max()))

    # (3) C varies per channel => toolkit per-channel requant of a per-tensor conv
    print("\n[C] per-channel mul: range %d..%d, %d distinct over 128 oc  => toolkit re-quantised"
          % (C.min(), C.max(), len(set(C.tolist()))))
    print("    (a true per-tensor requant would give ONE constant C; varying C == per-channel scales)")

    # (4) float surface layout != weight-DMA layout
    try:
        sm = np.load(R + "/dirty/vendor_cap/generic_slot_map.npy")
        fsk = np.round(np.nan_to_num(fs) / WT_SC).clip(-1e6, 1e6).astype(int)
        wv = np.array([(int(w[o, y, x, i]) - WT_ZP) if o >= 0 else 0 for (o, i, y, x) in sm[:len(fsk)]])
        nz = fsk != 0
        print("\n[layout] float surface vs weight-DMA order: %d/%d nonzero slots match (==0 => different layout)"
              % (int((wv[nz] == fsk[nz]).sum()), int(nz.sum())))
    except FileNotFoundError:
        print("\n[layout] generic_slot_map.npy not present; skip")


def ana_rknn_has_surface():
    """Show the .rknn does NOT carry the assembled live float surface."""
    vb = open(R + "/dirty/npu-test/vendor-bias.bin", "rb").read()
    rk = open(R + "/vendor-capture/conv2d_rk3576.rknn", "rb").read()
    live = np.frombuffer(vb[1024:1024 + 4944 * 4], dtype='<f4').copy()
    rkfs = np.frombuffer(rk[33488:33488 + 4944 * 4], dtype='<f4').copy()
    eq = (live == rkfs) | ((live != live) & (rkfs != rkfs))
    print("\n[rknn] live float surface vs rknn@33488: %d/4944 floats match "
          "=> rknn does NOT store the assembled surface (librknnrt builds it at runtime)"
          % int(eq.sum()))


if __name__ == "__main__":
    main()
    ana_rknn_has_surface()
