# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
import numpy as np, struct
WT_SC=3.91255
d=open("conv2d_rk3576.rknn","rb").read()
off=33488
# read a generous span
fa=np.frombuffer(d[off:off+256*4],dtype='<f4')
print("raw floats [0:40]:", np.round(fa[:40],4))
ints=fa/WT_SC
print("\n/wt_sc (rounded) [0:64]:")
print(np.round(ints[:64],3).astype(float))
print("\nare they near-integer?")
fr=np.abs(ints-np.round(ints))
print("max frac err over first 128:", fr[:128].max(), " mean:", fr[:128].mean())
ri=np.round(ints).astype(int)
print("\nint values [0:64]:", ri[:64].tolist())
print("int values [64:128]:", ri[64:128].tolist())
# load sw (per-oc weight sums) if present
import os
for p in ["/tmp/claude-1000/-home-parallels-Desktop-linux-rk3576-npu/c9200cd2-2a9c-41f7-8a3c-34bb47b6f421/scratchpad/sw.npy"]:
    if os.path.exists(p):
        sw=np.load(p); print("\nsw.npy shape",sw.shape,"first8:",sw[:8])
        # compare ints to sw
        print("ints[:8] vs sw[:8]:", ri[:8], sw[:8].astype(int) if sw.dtype.kind=='f' else sw[:8])
