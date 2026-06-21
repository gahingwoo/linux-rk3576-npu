# RK3576 CORE + DPU register map (differential)

Same method/sweeps as RK3576_CNA_MAP.md. KEY structural finding across ALL units
(CNA, CORE, DPU): RK3576 INSERTS registers relative to mesa's RK3588 map
(registers.xml) and thus SHIFTS subsequent offsets, while keeping mostly-analogous
value semantics. So the mesa port is largely (a) a per-unit offset remap + (b) a
few value-packing/const fixes, NOT a from-scratch re-derivation.

## CORE  (target 0x0801; vendor offsets vs mesa offsets)
RK3576 CORE block is mesa's CORE shifted by +0x8 from MISC_CFG onward:

| RK3576 off | meaning                              | mesa equivalent (off)        |
|------------|--------------------------------------|------------------------------|
| 0x3004     | 0x0000000e const (S_POINTER area)    | S_POINTER 0x3004             |
| 0x3018     | MAC/MISC cfg = 0x10000000 | mode     | MISC_CFG 0x3010              |
|            |   normal 0x01, depthwise 0x0a, in_ch=3 first-conv 0x81 | (mesa value is wrong/complex) |
| 0x301c     | (out_h-1)<<16 | (out_w-1)            | DATAOUT_SIZE_0 0x3014        |
| 0x3020     | out_ch-1                             | DATAOUT_SIZE_1 0x3018        |
| 0x3024     | clip truncate (0 for no-truncate)    | CLIP_TRUNCATE 0x301c         |

nsq (H128 W224): 0x301c=0x003f006f -> hi=0x3f=out_h-1=63, lo=0x6f=out_w-1=111.
mesa's DATAOUT_SIZE_0 value packing (HEIGHT high, WIDTH low) ALREADY matches; only
the offset (0x3014 -> 0x301c) and MISC_CFG value need fixing.

## DPU  (target 0x1001)  vendor offsets
| RK3576 off | meaning                                                |
|------------|--------------------------------------------------------|
| 0x4004     | 0x0e const                                             |
| 0x400c     | FEATURE_MODE_CFG = 0x40000004 | (depthwise? 0x08 : 0)   |
| 0x401c     | out_w * out_h   (DST surface size)                     |
| 0x4020     | out_w - 1                                              |
| 0x4024     | out_h - 1                                              |
| 0x402c     | out_ch - 1   (DATA_CUBE_CHANNEL)                       |
| 0x4030     | hi16 = out_ch-1 ; lo16 = 0x710 normal / 0x310 depthwise |
| 0x4034     | (out_h-1)<<16 | (out_w-1)                              |
| 0x4038     | notch/stride (normal 0x00120080, dw 0x00100092)        |
| 0x4044/0x4050 | BS ALU/OW cfg (depthwise differs)                   |
| 0x40ac     | surface notch (size-dependent)                         |
| 0x40b0     | OUT_CVT requant SCALE (per-layer quant; data-dependent — mesa computes via QNNPACK formula) |
| 0x40b4     | OUT_CVT shift (0x19 normal / 0x18 dw)                  |
| 0x40b8     | out_w * out_h (= 0x401c; dw variant *channels)         |
| 0x40c0     | 0x04440100 const                                       |
| 0x40d0     | 0x0040ffff const                                       |
| many const | 0x4044..0x40a8 = BS/BN/EW bypass + requant identity (per quant) |

mesa DPU offsets (FEATURE_MODE_CFG 0x400c, DST_BASE_ADDR 0x4020, DST_SURF_STRIDE
0x4024, DATA_CUBE_WIDTH 0x4030, HEIGHT 0x4034, CHANNEL 0x403c, BS_CFG 0x4040, ...
OUT_CVT_OFFSET/SCALE/SHIFT 0x4080/0x4084/0x4088). These do NOT line up with the
RK3576 offsets above (e.g. mesa 0x4020=DST addr, RK3576 0x4020=out_w-1) — the DPU
block is remapped too. The DST/weight/bias BASE_ADDR fields are 0 in the capture
(patched per-run): identify them by which RK3576 offsets hold the runtime addrs.

## Implication for the mesa rewrite
1. CNA: rewrite encoder per RK3576_CNA_MAP.md (two datapaths). Biggest change.
2. CORE: simplest — +0x8 offset shift + MISC_CFG value fix; values already right.
3. DPU: offset remap; geometry regs per table; keep mesa's requant math but place
   OUT_CVT at the RK3576 offsets; locate DST_BASE_ADDR offset (was 0 in capture).
The cleanest implementation is a RK3576-specific emit path keyed off the
chip, leaving the RK3588 path intact for that SoC.
