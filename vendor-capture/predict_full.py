#!/usr/bin/env python3
"""Mirror fill_regcmd_rk3576_normal() exactly and diff all 4 units vs the .rknn.
Usage: predict_full.py <tag> in=.. out=.. k=.. s=.. p=.. hw=.. [g=..]"""
import sys, struct

# quant + address regs: skip (mesa-computed / per-run)
SKIP = {0x1048,0x104c,0x1050,0x1054,0x1058,0x105c,0x1064,0x1084,0x1088,0x1110,
        0x4018,0x40ac,0x40b0,0x40b4,0x5020,0x5024}

def regs(path, tgt):
    d=open(path,'rb').read(); n=len(d)//8; w=struct.unpack("<%dQ"%n,d[:n*8])
    m={}
    for e in w:
        if ((e>>48)&0xffff)==tgt: m[e&0xffff]=(e>>16)&0xffffffff
    return m

def kv(a):
    d={"in":3,"out":32,"k":3,"s":2,"p":1,"hw":224,"g":1}
    for x in a: kk,vv=x.split("="); d[kk]=int(vv)
    return d

def predict(d):
    inw=inh=d["hw"]; k=d["k"]; s=d["s"]; p=d["p"]; ic=d["in"]; oc=d["out"]
    dw = d["g"]>1 and d["g"]==ic
    ow=(inw+2*p-k)//s+1; oh=ow
    surf=max(inw//4, ic//2); wbpk=(k*k*4) if dw else (ic*k*k*2)
    ohh=(oh-1)>>1; kw=0x0202 if k>=3 else 0
    C={0x1004:0xe,0x100c:(1 if dw else 0),0x1010:0xfff,0x1014:(s<<3)|s,
       0x1018:0x40000404,0x101c:(oc*k*k*2 if dw else ic*oc*k*k),
       0x1020:(oc if dw else ic)*k*k,0x1024:(kw<<16)|(1 if dw else oc-1),
       0x1028:((inw*inh*ic//64)<<16)|(ic-1),0x102c:((inw-1)<<16)|(inh-1),
       0x1030:(wbpk<<16)|(ow-1),0x1034:ow*oh-1,0x1038:7,0x103c:surf<<16,
       0x1040:0x10000000,0x1044:(inw<<16)|surf,0x1078:((inw-1)<<16)|(inh-1),
       0x107c:ic-1,0x1080:(0x101 if s==2 else(0x01010101 if dw else 0)),
       0x108c:0xf000f,0x1090:inw*4,0x1094:inw*inh,0x1098:inw*inh,
       0x118c:((inw-1)<<16)|(inh-1)}
    for z in (0x1060,0x1068,0x106c,0x1070,0x1074,0x109c,0x1100,0x1104,0x1140,0x1144):
        C[z]=0
    CO={0x3004:0xe,0x3018:0x10000000|(0x0a if dw else 1),
        0x301c:(ohh<<16)|(ow-1),0x3020:oc-1,0x3024:0}
    D={0x4004:0xe,0x400c:0x40000004|(8 if dw else 0),0x4010:0,0x4014:0,
       0x401c:ow*oh,0x4020:ow-1,0x4024:ohh,0x4028:0,0x402c:oc-1,
       0x4030:((oc-1)<<16)|(0x310 if dw else 0x710),0x4034:(ohh<<16)|(ow-1),
       0x4038:(0x100092 if dw else 0x120080),0x403c:0,0x4044:(0 if dw else 1),
       0x4048:0x80000000,0x404c:0x7fffffff,0x4050:(0x13133 if dw else 0x80011111),
       0x4058:0x80000000,0x405c:0x7fffffff,0x4060:0x903,0x406c:0x80000000,
       0x4070:0x7fffffff,0x4074:0x80000000,0x4078:0x7fffffff,0x407c:0x10041c1,
       0x4080:0,0x4084:1,0x4088:0x80000000,0x408c:0x7fffffff,0x4090:0,0x4094:0,
       0x409c:0,0x40a4:0x80000000,0x40a8:0x7fffffff,
       0x40b8:(ow*oh*7//2 if dw else ow*oh*3//2),0x40bc:0,0x40c0:0x4440100,
       0x40c8:0,0x40cc:0,0x40d0:0x40ffff}
    for r in list(range(0x4100,0x4124,4))+[0x4130]+list(range(0x4140,0x4158,4))+\
             [0x4160,0x4170,0x4174,0x4184,0x4188,0x418c,0x4190,0x4194]:
        D[r]=0
    R={0x5004:0xe,0x500c:ow-1,0x5010:ohh,0x5014:oc-1,0x5018:0,
       0x501c:(0x510 if dw else 0x710),0x5028:0,0x502c:0,0x5030:0,0x5034:0x41,
       0x5038:0,0x5040:0,0x5044:(0x40000012 if dw else 0x40000010),0x5048:0,
       0x504c:0,0x5064:0,0x506c:0,0x5078:0,0x507c:0}
    return {0x201:C,0x801:CO,0x1001:D,0x2001:R}

def main():
    tag=sys.argv[1]; d=kv(sys.argv[2:]); pred=predict(d)
    names={0x201:"CNA",0x801:"CORE",0x1001:"DPU",0x2001:"RDMA"}
    tot=bad=0
    for tgt in (0x201,0x801,0x1001,0x2001):
        real=regs(f"work/{tag}.rknn",tgt); pr=pred[tgt]
        for r in sorted(set(pr)|set(real)):
            if r in SKIP: continue
            pv=pr.get(r); rv=real.get(r)
            if pv is None or rv is None:
                if (pv or 0)==0 and (rv or 0)==0: continue
            tot+=1
            if pv!=rv:
                bad+=1
                print(f"  {names[tgt]:4} {r:04x}  pred={(pv if pv is not None else 0):08x}  real={(rv if rv is not None else 0):08x}")
    print(f"==== {tag}: {tot-bad}/{tot} match, {bad} mismatch ====")

main()
