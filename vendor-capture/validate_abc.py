#!/usr/bin/env python3
"""Byte-exact validation of the rkt_coefs.c per-axis ABC encoder against the
board-captured vendor buffer (dirty/npu-cap/out/{pw_oc,pw_ic}). Mirrors the
encoder: A=0x80*(sum(wq)+bias), B=0x80-wt_zp, C=round(2^14*wt_sc[oc]/max(wt_sc)),
interleaved [8xi32 A|8xi16 B|8xi16 C] per 8-oc group. Both pointwise convs
reproduce the captured 1024B ABC region byte-for-byte (1024/1024)."""
import numpy as np, struct, re
R="/home/parallels/Desktop/linux-rk3576-npu/dirty/npu-cap/out"
SCR="/tmp/claude-1000/-home-parallels-Desktop-linux-rk3576-npu/c9200cd2-2a9c-41f7-8a3c-34bb47b6f421/scratchpad"
OC=128
def cap(tag):
    d=open(f"{R}/{tag}/bo01.bin","rb").read()
    bo1=int(re.search(r"idx=1 handle=\d+ dma=0x([0-9a-f]+)",open(f"{R}/{tag}/meta.txt").read()).group(1),16)
    h=next(i for i in range(len(d)-10) if d[i]==0x20 and d[i+1]==0x50 and d[i+8]==0x24 and d[i+9]==0x50)
    v20=(((struct.unpack_from('<I',d,h+4)[0]&0xffff)<<16)|(struct.unpack_from('<I',d,h)[0]>>16))&0xffffffff
    a=(v20-bo1)&0xffffffff
    return d[a:a+OC*8], d[:a]
def enc(tag):
    abc,wsec=cap(tag); nper=len(wsec)//OC
    wq=(np.frombuffer(wsec,dtype=np.int8).astype(int).reshape(OC,nper)+0x80); sw=wq.sum(1)
    wt=np.abs(np.load(f"{SCR}/{tag}_w.npy").reshape(OC,-1)).max(1)/127.0
    out=bytearray(OC*8)
    for oc in range(OC):
        g,i=oc//8,oc%8
        struct.pack_into('<i',out,g*64+i*4,0x80*int(sw[oc]))
        struct.pack_into('<h',out,g*64+32+i*2,0x80)
        struct.pack_into('<h',out,g*64+48+i*2,int(16384*wt[oc]/wt.max()+0.5))
    return bytes(out),abc
if __name__=="__main__":
    for t in ("pw_oc","pw_ic"):
        e,c=enc(t); d=sum(x!=y for x,y in zip(e,c))
        print(f"{t}: {len(e)-d}/{len(e)} byte-exact {'OK' if d==0 else d}")
