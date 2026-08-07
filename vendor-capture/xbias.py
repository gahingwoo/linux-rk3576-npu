import struct, numpy as np, sys
def locate_abc(d, OC):
    for o in range(0, len(d)-DivPad(OC), 16):
        ok=True; Bs=[]; Cs=[]
        for oc in range(OC):
            g=o+(oc//8)*64; i=oc%8
            B=struct.unpack_from('<h',d,g+32+i*2)[0]
            C=struct.unpack_from('<h',d,g+48+i*2)[0]
            Bs.append(B); Cs.append(C)
            if abs(B)>1500 or not (0x1000<=C<=0x6000): ok=False; break
        if ok and len(set(Bs))>=min(3,OC-1) and len(set(Cs))>=min(3,OC-1):
            A=np.array([struct.unpack_from('<i',d,o+(oc//8)*64+(oc%8)*4)[0] for oc in range(OC)])
            return o, A, np.array(Bs), np.array(Cs)
    return None
def DivPad(OC): return ((OC+7)//8)*64
def main(path, OC):
    d=open(path,'rb').read()
    print(f"\n===== {path}  OC={OC}  filesize={len(d)} =====")
    r=locate_abc(d,OC)
    if not r:
        print("  ABC block NOT found"); return
    o,A,B,C=r
    grp=DivPad(OC)
    print(f"  ABC block @ off {o} (0x{o:x}), block size {grp}")
    print(f"  A[:8]={A[:8].tolist()}")
    print(f"  B[:8]={B[:8].tolist()}")
    print(f"  C[:8]={C[:8].tolist()}")
    # float surface expected right after ABC block (off o+grp) per mesa 0x5024 ptr math
    fs_off = o+grp
    # dump as fp32 a chunk after the block
    nfloat = 80
    raw=d[fs_off:fs_off+nfloat*4]
    f=np.frombuffer(raw,dtype='<f4')
    print(f"  float surface candidate @ {fs_off} (0x{fs_off:x}):")
    np.set_printoptions(precision=5,suppress=True,linewidth=130)
    print("   ", f[:40])
    # also scan whole file for fp32 arrays where many values in (0,400) and weight-like
    print(f"  -- scan whole file for dense fp32 runs (|v|<400, nonzero) --")
    fa=np.frombuffer(d[:len(d)//4*4],dtype='<f4')
    mask=(np.abs(fa)>1e-6)&(np.abs(fa)<400)&np.isfinite(fa)
    # find longest run
    runs=[]; s=None
    for i,m in enumerate(mask):
        if m and s is None: s=i
        elif not m and s is not None:
            if i-s>=8: runs.append((s,i-s)); 
            s=None
    runs.sort(key=lambda x:-x[1])
    for s,l in runs[:6]:
        print(f"     run @byte {s*4} len {l}: {fa[s:s+8]}")
if __name__=="__main__":
    main("conv2d_rk3576.rknn",128)
    main("work/tiny_oc8.rknn",8)
    main("work/tiny_oc16.rknn",16)
    main("work/tiny_ic8.rknn",8)
