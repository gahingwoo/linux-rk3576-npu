# RK3576 CNA register map (differential, first-conv / in_ch≤4 "ARGB" path)

Method: convert the same Conv2d to .rknn varying ONE parameter at a time
(`gen.py` + `conv.py`), diff the CNA regcmd (`diff.py`). Each row below is
anchored to ≥2 conversions where only the named parameter changed.

Sweep set (all in_ch=3 unless noted), params (in_w,in_h,out_w,out_h,k,s,p,out_ch):
  base  224 224 112 112 3 2 1 32
  hw112 112 112  56  56 3 2 1 32
  s1    224 224 224 224 3 1 1 32
  p0    224 224 111 111 3 2 0 32
  out64 224 224 112 112 3 2 1 64
  k1    224 224 112 112 1 2 0 32
  nsq   224 128 112  64 3 2 1 32   (H≠W: splits W/H fields)
  in8   224 224 112 112 3 2 1 32  in_ch=8  (switches to NORMAL channel path)

KEY: mesa (RK3588 map, registers.xml) emits CNA regs at DIFFERENT offsets and
DIFFERENT semantics. The vendor RK3576 stream writes regs mesa never touches
(0x1018,0x101c,0x103c,0x1048,0x108c,0x109c,0x118c) and at shared offsets the
meaning differs (vendor 0x1020=0x30, NOT DATAIN dims; 0x1010=0xfff, NOT
FEATURE_GRAINS). Only 0x1014 (stride) coincides with RK3588.

## CONFIRMED (clean, multi-point)
| off    | RK3576 meaning                                  | evidence |
|--------|--------------------------------------------------|----------|
| 0x1014 | (stride_y<<3) | stride_x                          | base 0x12=(2,2), s1 0x09=(1,1) |
| 0x1024 | hi16 = k const (0x0202 for k3, 0 for k1); lo16 = out_ch-1 | base lo 0x1f=31, out64 lo 0x3f=63 |
| 0x102c | (in_w-1)<<16 | (in_h-1)                           | base (223,223), nsq (223,127) |
| 0x1030 | lo16 = out_w-1 (hi16 = tiling)                    | base 0x6f=111, hw112 0x37=55, s1 0xdf=223, p0 0x6e=110 |
| 0x1044 | hi16 = in_w (lo16 = tiling/entries)              | base 0xe0=224, hw112 0x70=112 |
| 0x1078 | 0x29<<16 | (in_h-1)                               | base lo 0xdf=223, nsq lo 0x7f=127 |
| 0x1090 | ceil(in_w/16) * in_ch  (CBUF input line stride) | base 0x2a=14*3, hw112 0x15=7*3 |
| 0x1094 | in_h * reg[0x1090]                                | base 0x24c0=224*42, hw112 0x930=112*21, nsq 0x1500=128*42 |
| 0x1098 | = 0x1094                                          | same |
| 0x1028 | hi16 = in_h * 15 ; lo8 = 0x0b const              | base 0x0d20=224*15, nsq 0x0780=128*15 |

NOTE: 0x1090 was previously mislabeled "CLK_GATE=0x2a (engage gate)". It is NOT
clock-gating — it is the CBUF input line-stride and is SIZE-dependent. The
mesa hardcode 0x2a is correct ONLY for a 224-wide, 3-channel first conv.

## CONSTANT in the in_ch=3 first-conv path (hardcodable for layer 0 only)
| off    | value      | note |
|--------|------------|------|
| 0x1004 | 0x0000000e | |
| 0x1010 | 0x00000fff | |
| 0x1018 | 0x40000404 | in_ch=3; in8 -> 0x40000505 (precision/ARGB) |
| 0x1038 | 0x00000007 | weight kernels-ish |
| 0x1040 | 0x10000000 | CBUF_CON0 area |
| 0x1048 | 0x00071c70 | mesa hardcodes 0x000e38e0 (= 2x) -> WRONG |
| 0x104c | 0x7f807f80 | CVT (quant) |
| 0x1050 | 0x00017f80 | CVT |
| 0x1054 | 0xffffff80 | CVT |
| 0x1058 | 0xffffff80 | CVT |
| 0x105c | 0xffffff80 | CVT |
| 0x108c | 0x000f000f | |

## TILING-DERIVED (depend on toolkit CBUF banking; not yet closed-form)
0x100c (low nibble), 0x101c (out_ch & kernel & input-size), 0x1020,
0x1034 (hi ~ out_h), 0x103c (~ceil(in_w/16)), 0x1030 hi, 0x1044 lo,
0x1080, 0x1084, 0x118c.
These mirror what mesa already computes (input_banks, data_entries, atomics)
but packed at RK3576 offsets; next step is to match mesa's CBUF allocator
output (rkt_ml.h geometry already set to RK3576) to these.

## ADDRESS fields (patched per-run, 0 in the capture)
0x1070 = feature data base addr ; 0x1110 = weight (DCOMP_ADDR0).

---

# NORMAL channel path (in_ch>4: MobileNet depthwise + pointwise layers)

For in_ch>4 the toolkit uses a different (non-ARGB) datapath. Several CNA regs
keep their offset but change packing vs the first-conv path. Mapped from:
  in16 in_ch16 out32 k3 s2 p1 hw56  (single task, out28)
  pw   in_ch16 out32 k1 s1 p0 hw56  (single task, out56)
  in8  in_ch8  out32 k3 s2 p1 hw224 (MULTI-task / sliced — in_h field shows a
                                     slice height 0x59=89, not 223; use only to
                                     confirm in_w / kernel fields)

## CONFIRMED (normal path)
| off    | meaning                                          | evidence (in16 / pw) |
|--------|--------------------------------------------------|----------------------|
| 0x1014 | (stride_y<<3)|stride_x                            | in16 0x12, pw 0x09 |
| 0x1024 | hi16 = k word (0x0202 k3 / 0 k1); lo16 = out_ch-1 | both lo 0x1f=31 |
| 0x102c | (in_w-1)<<16 | (in_h-1)                           | in16/pw 0x0037_0037=55,55 |
| 0x1030 | hi16 = 32*k*k ; lo16 = out_w-1                    | k3 hi 0x120=288=32*9; k1 hi 0x20=32; lo in16 0x1b=27, pw 0x37=55 |
| 0x1044 | in_w<<16 | (in_w/4)                               | in16 0x0038_000e = 56,14 |
| 0x103c | hi16 = in_w/4                                     | in16 0x000e_0000 = 14 |
| 0x1090 | in_w * 4   (CBUF input line-stride, normal path)  | in16 0xe0=224=56*4, in8 0x380=896=224*4 |
| 0x1094 | in_w * in_h    (= 0x1098)                         | in16 0xc40=3136=56*56 |
| 0x1078 | (in_w-1)<<16 | (in_h-1)                           | in16 0x0037_0037 |
| 0x118c | (in_w-1)<<16 | (in_h-1)                           | in16 0x0037_0037 |

## Path differences (first-conv ARGB vs normal) at the SAME offset
| off    | first-conv (in_ch=3)          | normal (in_ch>4)        |
|--------|-------------------------------|-------------------------|
| 0x100c | 0x2000a006                    | 0x00000000              |
| 0x1018 | 0x40000404                    | 0x40000404 (in8 ..0505) |
| 0x1048 | 0x00071c70                    | 0x0000000b              |
| 0x104c..105c | CVT 7f80../ffffff80     | 0x00010001 / 0          |
| 0x1084 | 0x00808080                    | 0xffffff80              |
| 0x1090 | ceil(in_w/16)*in_ch           | in_w*4                  |
| 0x1078 | 0x29<<16 | (in_w-1)            | (in_w-1)<<16|(in_h-1)   |

## CHANNEL + DEPTHWISE direction (pointwise/dw sweep: pwA/pwB/pwC/dwA/dwB)
pwA in16 out32 k1 s1 p0 hw32 ; pwB in32 (in_ch only) ; pwC out64 (out_ch only)
dwA in32 g32 k3 s1 p1 hw32 ; dwB in32 g32 k3 s2 (stride only). All single-task.

| off    | meaning (normal in_ch>4)                          | evidence |
|--------|---------------------------------------------------|----------|
| 0x100c | bit0 = depthwise (CONV_MODE); 0 for normal conv   | dwA/dwB=1, pwB=0 |
| 0x101c | total weight bytes: normal in_ch*out_ch*k*k ; dw out_ch*k*k*2 | pwA 512=16*32*1, in16 4608=16*32*9, dwA 576=32*9*2 |
| 0x1020 | (dw? out_ch : in_ch) * k*k                         | pwA 0x10=16*1, pwB 0x20=32*1, in16 0x90=16*9, dwA 0x120=32*9 |
| 0x1024 | hi16 = k word (0x0202 k>=3 / 0 k1); lo16 = out_ch-1 (dw: lo=1) | pwC lo 0x3f=63 |
| 0x1028 | (in_ch*16)<<16 | (in_ch-1)                         | pwA 0x0100_000f, pwB 0x0200_001f |
| 0x1030 | hi16 = weight-bytes-per-kernel (normal in_ch*k*k*2 ; dw k*k*4) ; lo16 = out_w-1 | pwA hi 0x20=16*1*2, in16 hi 0x120=16*9*2, dwA hi 0x24=9*4 |
| 0x1034 | out_w*out_h - 1   (UNIVERSAL, all paths)          | base 0x30ff=112*112-1, in16 0x30f=28*28-1, dwB 0xff=16*16-1, nsq 0x1bff=112*64-1 |
| 0x103c | hi16 = input CBUF surface stride (~max(in_w/4, in_ch/2)) | pwA 8, pwB 16, in16 14 |
| 0x1044 | in_w<<16 | (same surface stride as 0x103c hi)     | pwA 0x0020_0008, pwB 0x0020_0010 |
| 0x107c | in_ch - 1                                          | pwA 0x0f=15, pwB 0x1f=31 |
| 0x1080 | surf stride word, stride-dependent (dwA 0x01010101, dwB 0x101) | open |

## REMAINING OPEN
0x1028 hi under k>1 (in16 hi=784, not in_ch*16 — has a k term); 0x1038 (=0x07
const so far); 0x1040 (CBUF bank cfg, 0x10000000 const in single-task cases);
0x1080 exact formula; the multi-task slicing (in8 at 224 split into tasks) — the
input_height field then carries a slice height, governed by the CBUF allocator.

## VERIFIED ENCODER SPEC (predict.py — 0 mismatch on 7 captures)
predict.py implements predict_cna(params) and is validated against pwA/pw/in16/
dwA/dwB/pwB/pwC: 34/34 geometry+channel+tiling+const regs match EXACTLY (only
quant 0x1048/0x104c-0x105c and addresses 0x1088/0x1110 left to mesa). Final CNA
formulas (normal in_ch>4 & depthwise; dw = groups==in_ch):
  ow=(inw+2p-k)//s+1 ; surf=max(inw//4, ic//2) ; wbpk = (k*k*4 if dw else ic*k*k*2)
  0x1004=0x0e ; 0x100c=(1 if dw else 0) ; 0x1010=0xfff ; 0x1014=(s<<3)|s
  0x1018=0x40000404 ; 0x101c=(oc*k*k*2 if dw else ic*oc*k*k) ; 0x1020=(oc if dw else ic)*k*k
  0x1024=((0x0202 if k>=3 else 0)<<16)|(1 if dw else oc-1)
  0x1028=((inw*inh*ic//64)<<16)|(ic-1)
  0x102c=((inw-1)<<16)|(inh-1) ; 0x1030=(wbpk<<16)|(ow-1) ; 0x1034=ow*oh-1
  0x1038=7 ; 0x103c=surf<<16 ; 0x1040=0x10000000 ; 0x1044=(inw<<16)|surf
  0x1078=((inw-1)<<16)|(inh-1) ; 0x107c=ic-1 ; 0x108c=0xf000f
  0x1080=(0x101 if s==2 else (0x01010101 if dw else 0))
  0x1090=inw*4 ; 0x1094=0x1098=inw*inh ; 0x118c=((inw-1)<<16)|(inh-1)
  zeros: 0x1060,0x1068,0x106c,0x1070,0x1074,0x109c,0x1100,0x1104,0x1140,0x1144
  quant (mesa QNNPACK): 0x1048,0x104c..0x105c ; addr: 0x1088 feat, 0x1110 weight

## VERIFIED CORE/DPU FORMULAS (normal+dw; ARGB first-conv differs)
CORE: 0x3004=0x0e ; 0x3018=0x10000000|(0x0a if dw else 0x01)
      0x301c=(((oh-1)>>1)<<16)|(ow-1)   [height field halved on normal path!]
      0x3020=oc-1 ; 0x3024=clip(0)
DPU:  0x4004=0x0e ; 0x400c=0x40000004|(0x08 if dw else 0)
      0x401c=0x40b8= round(ow*oh*(3.5 if dw else 1.5))  [output surface size; VERIFY]
      0x4020=ow-1 ; 0x4024=(oh-1)>>1 ; 0x402c=oc-1
      0x4034=(((oh-1)>>1)<<16)|(ow-1)
      0x40b0=OUT_CVT scale, 0x40b4=shift (mesa QNNPACK) ; 0x4018=output addr
RDMA: bias addr 0x5020 / 0x5024(+0x100) ; geometry 0x500c=ow-1,0x5010=(oh-1)?,0x5014=oc-1
OPEN/verify on flash: 0x40b8 multiplier (1.5/3.5), RDMA height field, multi-task tiling.

## SUMMARY — clean closed-form RK3576 CNA encoders ready to implement in mesa
stride 0x1014; depthwise 0x100c; weights 0x101c/0x1020/0x1030hi; channels
0x1024/0x1028/0x107c; in-dims 0x102c/0x1078/0x118c; out-dims 0x1030lo/0x1034;
in-CBUF 0x1090/0x1094/0x1098/0x103c/0x1044. This covers essentially all of the
CNA geometry/channel config for MobileNetV1's normal + depthwise layers.
