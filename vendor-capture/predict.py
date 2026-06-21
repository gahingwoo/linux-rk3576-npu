#!/usr/bin/env python3
"""
Offline validator for the RK3576 CNA encoder formulas.
Predict the CNA register values for a conv from its params, then diff against the
real .rknn extract. Lets us verify the Phase-2 encoder WITHOUT flashing.

Usage: predict.py <tag> in=.. out=.. k=.. s=.. p=.. hw=.. [g=..]
  compares work/<tag>.rknn CNA regs to predict_cna(params).
Only geometry/channel/tiling/const regs are checked; quant (104c-105c,1048) and
address (1088,1110) regs are listed as IGNORED.
"""
import sys, struct

IGNORE = {0x1048, 0x104c, 0x1050, 0x1054, 0x1058, 0x105c, 0x1064, 0x1084,
          0x1088, 0x1110}  # quant + address (per-model / per-run)

def cna_regs_from_rknn(path):
    data = open(path, "rb").read()
    n = len(data)//8
    words = struct.unpack("<%dQ"%n, data[:n*8])
    best=(0,0); i=0
    TGT={0x0201,0x0801,0x1001,0x2001,0x0041,0x0081}
    while i<n:
        if ((words[i]>>48)&0xffff) in TGT:
            j=i
            while j<n and ((words[j]>>48)&0xffff) in TGT: j+=1
            if j-i>best[1]: best=(i,j-i)
            i=j
        else: i+=1
    s,l=best; m={}
    for k in range(s,s+l):
        e=words[k]
        if ((e>>48)&0xffff)==0x0201:
            m[e&0xffff]=(e>>16)&0xffffffff
    return m

def predict_cna(d):
    inw,inh,k,s,p = d["hw"], d["hw"], d["k"], d["s"], d["p"]
    ic, oc, g = d["in"], d["out"], d.get("g",1)
    dw = (g>1 and g==ic)
    ow = (inw + 2*p - k)//s + 1
    oh = (inh + 2*p - k)//s + 1
    surf = inw*ic//64                       # input CBUF surface stride
    wbpk = (k*k*ic//8) if dw else (ic*k*k*2)  # weight bytes per kernel (0x1030 hi)
    # CBUF row window: only inw>=112 layers cap (measured on hardware)
    window = inh
    if inw >= 112:
        if ic <= 32: window = 91
        else:        window = 44 if s >= 2 else 45
    window = min(window, inh)
    capped = window < inh
    owin = (window - (1 if (dw and s == 1 and capped) else 0)) // s
    r = {}
    r[0x1004] = 0x0000000e
    r[0x100c] = 0x00000001 if dw else 0x00000000
    r[0x1010] = 0x00000fff
    r[0x1014] = (s<<3)|s
    r[0x1018] = 0x40000505 if capped else 0x40000404
    r[0x101c] = (oc*k*k*2) if dw else (ic*oc*k*k)
    r[0x1020] = (oc*k*k) if dw else (ic*k*k)
    r[0x1024] = ((0x0202 if k>=3 else 0)<<16) | (1 if dw else (oc-1))
    r[0x1028] = ((surf*window)<<16) | (ic-1)
    r[0x102c] = ((inw-1)<<16) | (window-1)
    r[0x1030] = (wbpk<<16) | (ow-1)
    r[0x1034] = ow*owin - 1
    r[0x1038] = 0x00000007
    r[0x103c] = surf<<16
    r[0x1040] = 0x14000000 if capped else 0x10000000
    r[0x1044] = (inw<<16) | surf
    r[0x1078] = ((inw-1)<<16) | (window-1)
    r[0x107c] = ic-1
    r[0x108c] = 0x000f000f
    r[0x1080] = 0x101 if s == 2 else ((0x01000101 if capped else 0x01010101) if dw else 0)
    r[0x1090] = inw*4
    r[0x1094] = inw*inh
    r[0x1098] = (inw*window + 3) & ~3
    r[0x118c] = ((inw-1)<<16) | (inh-1)
    for z in (0x1060, 0x1068, 0x106c, 0x1070, 0x1074, 0x109c,
              0x1100, 0x1104, 0x1140, 0x1144):
        r[z] = 0
    return r

def kv(args):
    d={"in":3,"out":32,"k":3,"s":2,"p":1,"hw":224,"g":1}
    for a in args:
        kk,vv=a.split("="); d[kk]=int(vv)
    return d

def main():
    tag=sys.argv[1]; d=kv(sys.argv[2:])
    real=cna_regs_from_rknn(f"work/{tag}.rknn")
    pred=predict_cna(d)
    allr=sorted(set(real)|set(pred))
    print("reg     predict   real      status")
    ok=bad=0
    for rr in allr:
        pv=pred.get(rr); rv=real.get(rr)
        ps="%08x"%pv if pv is not None else "----"
        rs="%08x"%rv if rv is not None else "----"
        if rr in IGNORE: st="ignore(quant/addr)"
        elif pv is None: st="not-predicted"
        elif rv is None: st="extra-predicted"
        elif pv==rv: st="OK"; ok+=1
        else: st="*** MISMATCH"; bad+=1
        if st!="OK":
            print("%04x  %-9s %-9s %s"%(rr,ps,rs,st))
    print("---- %d OK, %d mismatch (non-ignored, non-const-zero) ----"%(ok,bad))

if __name__=="__main__":
    main()
