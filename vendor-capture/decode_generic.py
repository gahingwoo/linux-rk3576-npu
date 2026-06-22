#!/usr/bin/env python3
"""
Decode the RK3576 generic weight-buffer layout from the three position-encoded
captures (gen_id_generic.py + run-idgen.sh):

    idg_A/bo01.bin  weight = ky*5+kx+1   -> byte decodes (ky,kx)
    idg_B/bo01.bin  weight = ic+1        -> byte decodes ic
    idg_C/bo01.bin  weight = oc+1        -> byte decodes oc

The vendor packs weights as (quant - 0x80), monotonic in the source value when the
byte is read as signed int8, so rank(byte) -> source value -> coordinate. For each
of the 51200 weight-DMA slots N we recover (oc,ic,ky,kx); the result is the exact
permutation Mesa's generic rkt_fill_weights must emit instead of the RK3588 order.

Usage: decode_generic.py [dir-holding idg_A idg_B idg_C]   (default .)
"""
import sys
import numpy as np

N = 51200
IC, OC, K = 16, 128, 5
base = sys.argv[1] if len(sys.argv) > 1 else "."


def blob(tag):
    b = open(f"{base}/idg_{tag}/bo01.bin", "rb").read()
    return np.frombuffer(b[:N], dtype=np.int8).astype(int)


def rank_decode(arr, n_real, tag):
    """byte value -> source weight (0 = pad/zero-point, 1..n_real = position)."""
    vals = sorted(set(arr.tolist()))
    print(f"  [{tag}] {len(vals)} distinct byte values (expect {n_real}+1 pad): "
          f"{vals[:6]}..{vals[-3:]}")
    # ascending signed byte == ascending source weight; smallest = weight 0 (pad)
    v2w = {v: i for i, v in enumerate(vals)}
    if len(vals) != n_real + 1:
        print(f"  [{tag}] WARNING distinct={len(vals)} != {n_real+1} — quant "
              f"collision/clip; decode may be off, inspect histogram")
    return np.array([v2w[x] for x in arr])


def main():
    A, B, C = blob("A"), blob("B"), blob("C")
    print("decoding...")
    wA = rank_decode(A, 25, "A ky,kx")   # 0=pad, 1..25 = ky*5+kx+1
    wB = rank_decode(B, 16, "B ic")      # 0=pad, 1..16 = ic+1
    wC = rank_decode(C, 128, "C oc")     # 0=pad, 1..128 = oc+1

    slot = [None] * N
    npad = 0
    for n in range(N):
        if wA[n] and wB[n] and wC[n]:
            P = wA[n] - 1
            slot[n] = (wC[n] - 1, wB[n] - 1, P // 5, P % 5)  # (oc,ic,ky,kx)
        else:
            npad += 1
    real = N - npad
    print(f"slots: {real} real, {npad} pad")

    # sanity: every (oc,ic,ky,kx) should appear exactly once
    seen = set(s for s in slot if s)
    print(f"distinct (oc,ic,ky,kx) covered: {len(seen)} / {OC*IC*K*K}")

    # show the first slots + infer the loop nesting (which coord varies fastest)
    print("first 32 real slots  N: (oc,ic,ky,kx)")
    shown = 0
    for n in range(N):
        if slot[n] and shown < 32:
            print(f"  {n:5d}: {slot[n]}")
            shown += 1

    # derive per-coordinate stride: how far apart consecutive values of each coord
    # at the other coords fixed — reveals the nesting order for the C loop.
    np.save(f"{base}/generic_slot_map.npy",
            np.array([s if s else (-1, -1, -1, -1) for s in slot]))
    print(f"wrote {base}/generic_slot_map.npy  (51200 x 4)")


if __name__ == "__main__":
    main()
