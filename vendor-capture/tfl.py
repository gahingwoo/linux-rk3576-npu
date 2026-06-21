#!/usr/bin/env python3
"""Minimal TFLite flatbuffer reader (no schema module) to pull tensors,
quantization, operators and buffer data for offline golden computation."""
import struct, numpy as np
from flatbuffers import table, encode, number_types as N

class M:
    def __init__(s, path):
        s.buf = bytearray(open(path,'rb').read())
        root = encode.Get(N.UOffsetTFlags.packer_type, s.buf, 0)
        s.model = table.Table(s.buf, root)
    def _f(s, t, fid):  # field offset within table t
        return t.Offset(4 + 2*fid)
    def _tbl(s, t, fid):
        o = s._f(t, fid)
        return None if o==0 else table.Table(t.Bytes, t.Indirect(o + t.Pos))
    def _vec_len(s, t, fid):
        o = s._f(t, fid); return 0 if o==0 else t.VectorLen(o)
    def _vec_tbl(s, t, fid, i):
        o = s._f(t, fid); base = t.Vector(o)
        off = base + i*4
        return table.Table(t.Bytes, t.Indirect(off))
    def _vec_i32(s, t, fid):
        o = s._f(t, fid)
        if o==0: return []
        base = t.Vector(o); n = t.VectorLen(o)
        return [struct.unpack_from('<i', t.Bytes, base+i*4)[0] for i in range(n)]
    def _str(s, t, fid):
        o = s._f(t, fid)
        return b'' if o==0 else t.String(o+t.Pos)
    def _f32_vec(s, t, fid):
        o = s._f(t, fid)
        if o==0: return None
        base = t.Vector(o); n = t.VectorLen(o)
        return np.frombuffer(t.Bytes, '<f4', n, base).copy()
    def _i64_vec(s, t, fid):
        o = s._f(t, fid)
        if o==0: return None
        base = t.Vector(o); n = t.VectorLen(o)
        return np.frombuffer(t.Bytes, '<i8', n, base).copy()

    def subgraph0(s):
        return s._vec_tbl(s.model, 2, 0)   # Model.subgraphs[0]
    def buffers(s):
        return s.model  # use lazily
    def buffer_data(s, bi):
        b = s._vec_tbl(s.model, 4, bi)     # Model.buffers[bi]
        o = s._f(b, 0)                     # Buffer.data
        if o==0: return None
        base = b.Vector(o); n = b.VectorLen(o)
        return np.frombuffer(b.Bytes, np.uint8, n, base).copy()

m = M('mobilenet_v1_1.0_224_quant.tflite')
sg = m.subgraph0()
ntensors = m._vec_len(sg, 0)
nops = m._vec_len(sg, 3)
print('tensors', ntensors, 'ops', nops)
# dump first 6 tensors
for i in range(min(6, ntensors)):
    t = m._vec_tbl(sg, 0, i)
    shape = m._vec_i32(t, 0)
    name = m._str(t, 3).decode('ascii','replace')
    q = m._tbl(t, 4)  # quantization
    sc = m._f32_vec(q, 2) if q else None
    zp = m._i64_vec(q, 3) if q else None
    buf = m._f(t, 2) and struct.unpack_from('<i', t.Bytes, m._f(t,2)+t.Pos)[0]
    print(f"T{i} shape={shape} buf={buf} scale={None if sc is None else sc[:3]} zp={None if zp is None else zp[:3]} {name[:40]}")
# first op inputs/outputs
op0 = m._vec_tbl(sg, 3, 0)
print('op0 inputs', m._vec_i32(op0, 1), 'outputs', m._vec_i32(op0, 2))

# ---- conv0 golden ----
def tinfo(ti):
    t = m._vec_tbl(sg, 0, ti)
    shape = m._vec_i32(t, 0)
    q = m._tbl(t, 4)
    sc = m._f32_vec(q, 2) if q else None
    zp = m._i64_vec(q, 3) if q else None
    bufid = struct.unpack_from('<i', t.Bytes, m._f(t,2)+t.Pos)[0]
    typ = struct.unpack_from('<b', t.Bytes, m._f(t,1)+t.Pos)[0] if m._f(t,1) else 0
    return shape, sc, zp, bufid, typ

iin, iw, ib, io = 88, 8, 6, 7
shp_i, sc_i, zp_i, _, _ = tinfo(iin)
shp_w, sc_w, zp_w, bw, _ = tinfo(iw)
shp_b, sc_b, zp_b, bb, _ = tinfo(ib)
shp_o, sc_o, zp_o, _, _ = tinfo(io)
print("IN ", shp_i, "scale", sc_i, "zp", zp_i)
print("WT ", shp_w, "nscale", None if sc_w is None else len(sc_w), "zp", zp_w[:1] if zp_w is not None else None)
print("BI ", shp_b, "scale", None if sc_b is None else sc_b[:1])
print("OUT", shp_o, "scale", sc_o, "zp", zp_o)

W = m.buffer_data(bw).astype(np.int32).reshape(shp_w)   # [32,3,3,3] uint8 (oc,kh,kw,ic)
B = m.buffer_data(bb)
B = np.frombuffer(B.tobytes(), '<i4')                    # bias int32
from PIL import Image
img = np.array(Image.open('grace_hopper.jpg').resize((224,224)).convert('RGB'), dtype=np.int32)  # HWC
inz = int(zp_i[0]); wz = int(zp_w[0]); oz = int(zp_o[0])
si = float(sc_i[0]); so = float(sc_o[0])
sw = sc_w  # per-axis array len 32 (or 1)
# conv stride2 pad SAME, k3, ic3, oc32
xi = (img - inz)                                         # [224,224,3]
# pad SAME for stride2 k3 out112: pad so that output=112
# tf SAME: out=ceil(224/2)=112; pad_total = max((112-1)*2+3-224,0)=1 -> pad top0/left0? tf pads (0,1)
pad = np.zeros((225,225,3), np.int32); pad[0:224,0:224,:] = xi
out = np.zeros((112,112,32), np.float32)
for oc in range(32):
    wq = W[oc] - wz                                     # [3,3,3]
    s = sw[oc] if len(sw)>1 else sw[0]
    acc = np.zeros((112,112), np.int64)
    for ky in range(3):
        for kx in range(3):
            for ic in range(3):
                acc += pad[ky:ky+224:2, kx:kx+224:2, ic][:112,:112] * wq[ky,kx,ic]
    real = (acc + B[oc]).astype(np.float64) * (si * float(s))
    out[:,:,oc] = np.clip(real, 0, 6)                   # ReLU6
q = np.clip(np.round(out/so) + oz, 0, 255).astype(np.uint8)
print("golden conv0 out[0,0,:8] uint8 =", q[0,0,:8])
print("golden conv0 out stored(-0x80) =", (q[0,0,:8].astype(int)-128))
print("golden conv0 sat255 frac =", (q==255).mean(), " zero frac =", (q==0).mean(), " mid frac=", ((q>0)&(q<255)).mean())

# ---- reproduce NPU "mesa-naive" conv0 (weights-0x80, NO weight-zp correction) ----
Bq = B.astype(np.int64)
M = si * float(sw[0]) / so
# (a) naive: subtract 0x80 from BOTH in and wt (mesa current), bias = Bq (tflite bias)
acc_n = np.zeros((112,112,32), np.int64)
xin = (img - 128)                    # in - 0x80
pad2 = np.zeros((225,225,3), np.int64); pad2[0:224,0:224,:] = xin
for oc in range(32):
    wn = (W[oc] - 128)
    a = np.zeros((112,112), np.int64)
    for ky in range(3):
        for kx in range(3):
            for ic in range(3):
                a += pad2[ky:ky+224:2, kx:kx+224:2, ic][:112,:112] * wn[ky,kx,ic]
    acc_n[:,:,oc] = a + Bq[oc]
out_n = np.clip(np.round(acc_n * M) + 0, 0, 255).astype(np.uint8)
print("NAIVE(wt-128,bias=tflite) out[0,0,:8] uint8 =", out_n[0,0,:8], " stored=", out_n[0,0,:8].astype(int)-128)
print("NAIVE sat255 frac =", (out_n==255).mean())

# (b) correct math but weights packed as (wt - wt_zp=151): does golden survive int8 clamp of weights?
wzp=151
clamped = np.clip(W.astype(int)-wzp, -128, 127)
overflow = ((W.astype(int)-wzp) < -128).mean()
print("weights (wt-151) int8 overflow frac =", overflow)

# (c) hardware-correct with weight-zp compensation term per output:
# real_acc = naive_acc + (0x80 - wt_zp)*sum_window(in-0x80)  ... show it matches golden

# ---- all conv-layer weight zero points (is asymmetric systemic?) ----
print("\n=== per-conv-op weight zp (asymmetric if != 128) ===")
for opi in range(nops):
    op = m._vec_tbl(sg, 3, opi)
    ins = m._vec_i32(op, 1)
    if len(ins) < 2: continue
    wt = ins[1]  # weight tensor index (conv: [in, weight, bias])
    t = m._vec_tbl(sg, 0, wt)
    q = m._tbl(t, 4)
    if not q: continue
    zp = m._i64_vec(q, 3)
    sc = m._f32_vec(q, 2)
    shp = m._vec_i32(t, 0)
    if zp is None: continue
    nm = m._str(t,3).decode('ascii','replace')
    if 'weight' in nm.lower() or 'Conv2D' in nm:
        print(f"op{opi:2d} wt_zp={int(zp[0]):3d} nscale={len(sc) if sc is not None else 0} shape={shp} {nm[:45]}")
