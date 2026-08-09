# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: MIT
import numpy as np, struct, sys
path=sys.argv[1]; OC=int(sys.argv[2]); IC=int(sys.argv[3]); K=int(sys.argv[4])
d=open(path,'rb').read()
w=np.load(path.replace('.rknn','_w.npy')); b=np.load(path.replace('.rknn','_b.npy'))
print(f"=== {path} OC={OC} IC={IC} K={K} ===")
print("known w[:,0,0,0]=",w[:,0,0,0]," bias=",b)
fa=np.frombuffer(d[:len(d)//4*4],dtype='<f4')
mask=np.isfinite(fa)&(np.abs(fa)>1e-7)&(np.abs(fa)<1e4)
# weight-like fp32 runs
runs=[];i=0
while i<len(mask):
    if mask[i]:
        j=i
        while j<len(mask) and mask[j]: j+=1
        if j-i>=4: runs.append((i,j-i))
        i=j
    else: i+=1
runs.sort(key=lambda x:-x[1])
print("\ntop fp32 runs (byteoff,len):")
for s,l in runs[:8]:
    print(f"  @{s*4} len {l}: {np.round(fa[s:s+min(l,16)],5)}")
# try to locate ABC: scan for int32 A whose /something ~ structured; print candidate 64B groups
# Heuristic: find region where consecutive i16 pairs look like small B and C~0x1000-0x6000
print("\n-- scan for ABC group (B small, C in 0x800..0x7000) --")
ng=(OC+7)//8
for o in range(0,len(d)-ng*64,4):
    ok=True;Bs=[];Cs=[];As=[]
    for oc in range(OC):
        g=o+(oc//8)*64;ii=oc%8
        A=struct.unpack_from('<i',d,g+ii*4)[0]
        B=struct.unpack_from('<h',d,g+32+ii*2)[0]
        C=struct.unpack_from('<h',d,g+48+ii*2)[0]
        As.append(A);Bs.append(B);Cs.append(C)
        if abs(B)>2000 or not(0x400<=C<=0x7000): ok=False;break
    if ok and len(set(Cs))>=min(2,OC):
        print(f"  ABC@{o}(0x{o:x}): A={As} B={Bs} C={Cs}")
        break
