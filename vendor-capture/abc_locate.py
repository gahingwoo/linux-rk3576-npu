import struct, numpy as np
def locate_abc(path, OC=128):
    d=open(path,'rb').read()
    for o in range(0, len(d)-1024, 16):
        ok=True; Bs=[]; Cs=[]
        for oc in range(OC):
            g=o+(oc//8)*64; i=oc%8
            B=struct.unpack_from('<h',d,g+32+i*2)[0]
            C=struct.unpack_from('<h',d,g+48+i*2)[0]
            Bs.append(B); Cs.append(C)
            if abs(B)>1500 or not (0x1000<=C<=0x6000): ok=False; break
        if ok and len(set(Bs))>3 and len(set(Cs))>3:
            A=np.array([struct.unpack_from('<i',d,o+(oc//8)*64+(oc%8)*4)[0] for oc in range(OC)])
            return o, A, np.array(Bs), np.array(Cs)
    return None
