# RK3576 NPU (rocket + Mesa Teflon) — conv0 zero-output: complete findings

**Status:** **the wall is broken.** The bug was the SDP coefficient (bias/requant) buffer in
`rkt_coefs.c`. With it fixed, the live mainline rocket + Teflon path computes a **rich conv
output** (distinct 236–256, full range) instead of the grey zero-point rail — both with the
vendor's exact bytes and with the driver's own regenerated buffer. Remaining: byte-exact.
The dominant error is the **float surface**, and for this **per-tensor** `conv2d` it needs the toolkit's exact
per-channel re-quantised values (proven: shuffling them keeps the sparse structure but still gives maxdiff=255) — a
sparse, compiler-chosen table that is **not derivable from the tflite** (blob-only). But `conv2d` is a synthetic
per-tensor test; the actual target, **MobileNet, is per-axis**, and the per-channel float surface decodes cleanly to the
dequantised weights (the `idg` captures, months ago). **Next direction: move the encoder + the measured maxdiff loop onto
a per-channel conv, where the float surface is the weights — not the welded-shut per-tensor `conv2d`.**

- HW: Radxa ROCK 4D (RK3576). Stack: mainline **rocket** accel driver + **Mesa Teflon**.
- Reference: vendor `rknpu` + RKNN runtime runs the same MobileNetV1 correctly on the same board.
- CPU ref: Top-1 653 / conf 0.887. NPU: Top-1 0, output all zero-point.

## 2026-06-24 (measurement unblocked + bisect) — the float surface is the dominant error, not A/B/C

Unblocked the byte-for-byte `maxdiff` (the board wedged before the userspace line — the post-job pm_runtime autosuspend
powers the NPU off, `nputop` fails to idle, a cpu rail times out `-110`, console dies). Fix is **sysfs, no kernel
rebuild**: force runtime PM off so the NPU stays powered through the test (`/sys/devices/**/npu*/power/control = on`).
Both segments + the END marker now print.

The number is sobering: the driver's own contiguous-A + dense-float reconstruction is `distinct=256` but **maxdiff=255,
mean|diff|=78, exact=0.7%** — it computes and is almost entirely wrong (datapath tolerance flatters "lights up" into
looking like "correct"). Bisected with two hybrid buffers (loaded via `ROCKET_BIAS_FILE`): **vendor A/B/C + my dense
float → maxdiff=255, distinct=12** (near-degenerate). So even with the *exact* per-channel terms, my float surface is
wrong → **the float surface tiling is the dominant error.** (My A/B/C is also wrong — only 14.9% byte-identical to the
vendor's, `0x80*(sw+bias)` is far off — but secondary.) The vendor float region is **sparse**: 626 nonzero of 4944
slots, and the values don't match any weight order I can read — so the per-tensor `conv2d` float surface likely isn't the
dense dequant-weight array the per-channel `idg` captures decoded months ago. Cracking that sparse scatter is the
remaining hard piece — but it's now **measurable** (drive the hybrid's maxdiff down). Harness: `S97` power-keepon +
`test_conv.py` os._exit; hybrids in `dirty/npu-test/H-myfloat.bin`, `H-myABC.bin`.

## 2026-06-24 (BREAKTHROUGH) — the grey broke: the live driver computes a rich conv from a fixed bias buffer

After confirming the bias buffer is the bug, fixed it in `rkt_coefs.c` and ran the **live** Teflon path (not replay) on
`conv2d-cal`, reading the kernel output readback:

- **Milestone (load the known-good bytes):** `rkt_coefs.c` loads `vendor-bias.bin` verbatim → `buf out distinct=256
  nz=4091/4096 min=00 max=ff` — a real feature map on the live mainline rocket + Teflon driver. Proves the road is
  paved: regcmd, weights, datapath, submit, op_en (broadcast, writes ENABLE_MASK 0xf008 → `exec_ever=0xf`) are all fine;
  the only gap was generating this buffer.
- **The rewrite (the driver's own buffer):** removed the wrong interleaved `[8×i32 A|8×i16 B|8×i16 C]` layout; the new
  default writes **contiguous `A[128]`@0 + `D[128]`@512 (≈A) + a dequant-weight float surface** (`wt_sc*(q-wt_zp)`)
  @`groups*64`. With no file, mesa's own buffer (`bia` A[0]=0x5100=`0x80*(sw+bias)`) → `buf out distinct=236
  nz=3231/4096` — a rich map. **The open driver now generates a working coefficient buffer; the chip computes from it.**

Real upstreamable fixes landed: the interleaved→contiguous BS layout, the non-zero dequant float surface (was always
zero), and the bias-BO size (the old 1280B caused an OOB RDMA read). **NOT yet byte-exact:** rewrite distinct=236 / head
`df00ba00` vs vendor distinct=256 / head `80808080` — `A` is a best-effort `0x80*(sw+bias)` (≠ the vendor operand) and
the float fill is dense vs the vendor's sparse tiling. The surface is tolerant (x0.5/shuffle still compute), which is why
the approximation already runs. Correctness (maxdiff) is unmeasured — the board wedges in BO cleanup before the userspace
line. Next: flush the maxdiff past the wedge (`os._exit` in test_conv.py), then refine the `A` operand encoding + float
tiling toward byte-exact.

## 2026-06-24 (later) — `core wt_rd=0` was a RED HERRING; the bias buffer is the bug; the SDP spec is in the TRM

Re-grounded by replaying the vendor's exact bytes through the kernel and reading the **output**, not the counter:

- **`core wt_rd=0` is a red herring.** The run that COMPUTED a real feature map (`OUT: distinct=98`, 99% nonzero, head
  `0a0b0b05`) shows `core wt_rd=0` too. So that perf counter does not measure CMAC weight reads; `wt_rd=0` is normal.
  Runs #4–#7 (per-unit op_en, enable_mask, BO size, float-const fill) all chased this — wasted. The valid oracle is the
  OUTPUT (distinct under the non-saturating shift, or maxdiff vs CPU), never a perf counter. (The BO-size enlargement is
  still a real fix — the OOB read was real — keep it.)
- **The bias buffer is the bug (clean A/B).** Same vendor weights, same regcmd, swap ONLY the bias: vendor bias →
  `distinct=98 COMPUTED`; mesa bias → `distinct=2 DEGENERATE`. Nothing else differs. After weeks of the bug sliding
  across the weights / dispatch / geometry / a lying counter, it is definitively the SDP coefficient buffer (`rkt_coefs.c`).
  (Earlier I "exonerated requant" — that was the OUT_CVT 0x40ac/b0/b4, which *is* correct; I wrongly conflated it with
  the 0x5020/0x5024 BS buffer, which is the bug.)
- **The missing SDP spec is in the allbilly RK TRM.** `A` doesn't fit `sw`/`bias` (R²=0.002) because it isn't a bias
  formula — it's a **BS-datapath operand**. The TRM: `brdma_data_use` (0x501c) selects which per-channel operands the
  DPU_RDMA reads (bit0 ALU, bit1 CPEND, bit2 MUL, bit3 TRT); `bs_alu_src`/`bs_mul_src`=1 fetch the ALU/MUL operands
  **per-channel from the 0x5020 BS surface**; `out = ((in ALU_op alu_operand) * mul_operand) >> shift`; `erdma_data_mode`
  = per-channel vs **per-channel-by-pixel**. So vendor-bias.bin = `A[128]`+`D[128]` (two per-channel scalar operands) +
  the float surface (the MUL operand in per-channel-**by-pixel** mode = the dequantised weights, one per (ch,tap) — which
  is why there are 4944 floats, not 128). The format is now theory-grounded; the remaining work is mapping each operand
  to its slot and writing the encoder in `rkt_coefs.c`, tested against the OUTPUT.

## 2026-06-24 (cont.) — runs #2–#5: the wall is `core wt_rd=0` (CBUF→CMAC), and an evidence-based way out  *(superseded by the section above — `core wt_rd` is a red herring)*

Built `conv2d-cal` (non-saturating) and ran a sequence, reading the kernel perf counters / `cnalive` as the oracle
(never `distinct`). Each run corrected the previous hypothesis:

- **4-register geometry fix** (generic path `0x1018/0x1024/0x1040/0x1080` → vendor) took effect but did **not** turn
  the MAC on — still `core wt_rd=0`. So the geometry *values* were never the wall.
- **op_en, three ways:** broadcast (units engage, `wt_rd=0`); full strip (geometry sits, `exec_ever=0`, units never
  engage); per-unit `0x_008`=`0x1d` (units engage, `wt_rd=0`). The engage *mechanism* does not determine the weight read.
- **Reframe (kernel patch 0014):** the in-stream broadcast op_en (regcmd `tgt 0x81`/`reg 0x08`) is **not** a PC op_en —
  `tgt 0x81` → base `0xf000`, so it writes `0xf008` = the global RKNPU **ENABLE_MASK** (`0x1d`). So "it restarts the PC"
  (mesa's own `rkt_ml.c` comment, and my reasoning) was wrong; the `ds0_first` 0/-1 swings were a sampler **timing
  confound** (the task finishing before the 1-sample poll), not real latch/no-latch.
- **`enable_mask=0x1d`** (kernel CPU-writes `0xf008` before OP_EN, like the vendor) → **hard hang** (the ENABLE_MASK
  auto-start engages but deadlocks — no completion, no readback).
- **Persistent wall across every run:** `core wt_rd=0` — the CMAC reads **zero** weights from CBUF while the CNA loads
  it (`top wt_rd=3200`). This is the conv0 CBUF→CMAC channel-bank wall, now reached from `conv2d`.

Offline weight-BO compare: mesa's emitted weight BO differs from `vendor-weights.bin` in **97%** of bytes (every `oc`
differs). Inconclusive on its own — a value difference does not explain a *structural* `wt_rd=0`, and `vendor-weights.bin`
may be an imperfect extraction.

**The way out (evidence-based, not more param-spraying).** The load-bearing fact: `replay_rocket` (vendor regcmd +
vendor weights + vendor bias) **computes** on this exact kernel (`wt_rd>0`, real feature map); live mesa — whose regcmd
now matches the vendor's — does not. So the cause is isolable by swapping **one component at a time** on the same
harness while reading **`core wt_rd`** (the structural oracle). The earlier bisection used `distinct` (the invalid
metric), so re-running it with `core wt_rd` is **not** redundant work:
- **Thread A (harness bisection):** `replay_mesa`, regcmd held at vendor-patched, swap weights/bias mesa↔vendor, read
  `core wt_rd` → pins the `wt_rd=0` cause to regcmd vs weights vs bias vs submit.
- **Thread B (offline, no flash):** use the position-encoded captures (`idg_A`: weight = `ky*5+kx+1`) to read mesa's
  actual weight tiling against the vendor's CBUF bank order — decides whether the 97% diff is a real tiling/bank
  mismatch (→ the CMAC reads an empty bank) or extraction noise. `enable_mask` must be left off (it hangs).

## 2026-06-24 — the ruler was broken: it's an empty MAC, not the requant (and the floats below are now in question)

**Reversal, and not a small one.** Everything below this section was measured with `distinct` (how many
different output values come back) as the stand-in for "did it compute". That stand-in does not survive
contact with two facts found today, so the requant/float-surface conclusions below are **suspect for
`conv2d` and have to be re-read with that in mind.**

1. **`distinct`/`head` were never a correctness test.** The output *head* is the same (`d6c4afd8`) whether
   the weights are correct or **shuffled** — provably-wrong input produces the same fingerprint, so the
   fingerprint never read correctness. And a CPU reference of the exact int8 op (plain `numpy`, quant params
   read straight off the `.tflite` — note `parse_tflite.py` reads the quant fields off-by-one; the real layout
   is `min=0/max=1/scale=2/zero_point=3`) shows the **correct** output of `conv2d.tflite` **saturates**: on the
   harness ramp, `acc` runs to ±170000, `M=1.299` pins ~100% of it to `0x7f/0x80`, distinct≈5. The synthetic
   model's `out_sc` is simply too small for its random weights. So on this model a correct conv and a broken
   constant-fill **both** collapse to `distinct≤2` — the metric cannot tell them apart. Months of "make distinct
   big like the vendor's 252" were chasing a target (`252`) that is **not** the correct answer; it is the vendor
   requant running at a 3648× finer scale (shift 26 vs 14), which dodges the saturation. Correct, here, is grey.

2. **Calibrate the model, and the grey turns out to be an empty multiply, not a hot requant.** Patched
   `conv2d.tflite` → `conv2d-cal.tflite` (only `T3`: `out_sc 0.0235→32`, `out_zp 0→128`; weights/bias/inputs
   byte-identical) so the *correct* output is a rich non-saturated map (`distinct~256`, ~1% saturated). On the
   board, mesa's native output is **pinned to `out_zp` (`0x7f/0x80` = 127/128) with no `00`/`ff` tails** → the
   accumulator is ≈0. The chip's own regcmd shows mesa computing OUT_CVT **correctly** for the calibrated model
   (`0x40b0`=32052, `0x40b4`=25, `0x40ac`=0 ⇒ `M=in_sc·wt_sc/32` and `out_zp=128`). Since the MAC is upstream of
   OUT_CVT and independent of `out_sc`/`out_zp` — the only things changed — the **original** model's `distinct=2`
   was **also MAC≈0**, never requant saturation. **The requant is exonerated for `conv2d`.** The coefficients are
   all in DRAM (readbacks real: in 251 / wt 199 / bia 127 distinct) and the engine runs — and the product is zero.

3. **Coherency ruled out, bug localized to four geometry registers.** `replay_rocket` computes (MAC≠0) with the
   vendor regcmd on the *same* kernel, so the NPU reads DRAM fine — MAC=0 is not coherency. Diffing the fresh
   native regcmd against the vendor's, the only config divergences are **four CNA geometry registers** in mesa's
   generic path `fill_regcmd_rk3576_normal` (`rkt_regcmd.c`), calibrated on stride-1/3×3 shapes and wrong for this
   5×5 stride-2 conv: `0x1024` `k_word` hard-codes the kernel size to 3 (`0x0202`, wants `0x0404`); `0x1018`
   (`0x...505`→`0x...404`), `0x1040` CBUF_CON0 (`0x14000000`→`0x10000000`), `0x1080` SURF_STRIDE
   (`0x00000101`→`0x02020101`) — each confirmed against both the vendor capture and the hard-coded conv0 path.

**FIX (applied, NOT yet board-confirmed):** corrected the four formulas in `rkt_regcmd.c`, conditional on
`s==2`/`k≥5` so MobileNet's 1×1 and 3×3-stride-1 layers are untouched; rebuilt `libteflon.so`. The board hangs
after one submit (it always has) and hung before the userspace verdict printed, so **whether this turns the MAC
on is still an open question the board hasn't answered.** Watch the kernel `out task=0 … distinct=` readback: a
real spread off `out_zp` = the geometry fix works; still `0x7f/0x80 distinct=2` = MAC still 0, next lever is the
mesa-only in-stream op_en (`tgt 0x81 reg 0x08`) the vendor doesn't emit.

> **Caveat on the sections below.** The `0x5024` float-surface decode (2026-06-23 late) was done under the
> vendor regcmd, where the MAC *does* run, and judged by `distinct` — so it may describe a real per-axis
> mechanism *or* an artifact of the vendor's finer output scale. For the per-tensor `conv2d` the bug is now
> upstream of all of it (empty MAC / geometry). Kept below as the record, not as a settled conclusion.

## 2026-06-23 (late) — the SDP requant buffer format, cracked from controlled captures

The whole-session bisection had localised the saturation to the **SDP bias/requant buffer**
(`rkt_coefs.c`): with the vendor's buffer the pipeline computes, with Mesa's it saturates, and
**zeroing the `0x5024` "second buffer" alone re-saturates** (`iso-noFloat` → `distinct=2`), so that
region is load-bearing, not padding. Three purpose-built convs were captured on the board to read the
buffer the vendor runtime actually uploads (`dirty/ABC_test/{iso_scale,iso_sum,iso_bias}`, all
conv2d-shaped `16→128 5×5 s2`, each varying exactly one quant axis), plus three position-encoded
captures (`dirty/vendor_cap/idg_{A,B,C}`, weight = `ky*5+kx+1` / `ic+1` / `oc+1`). The per-channel
requant buffer (`bo1[51200:]`) decodes cleanly:

| field | offset | what it is | evidence |
|---|---|---|---|
| **A** | `0` | `int32[128]`, **contiguous** per-channel term ≈ `0x80*(sw+bias)` | `iso_sum`: `A` vs weight-sum **R²=1.0000**; `iso_scale`: slope **127.93 ≈ 0x80**; `iso_bias`: `A` linear in bias |
| **B** | `512` | **one int32 scalar** = `0x80 - wt_zp` | `iso_scale` wt_zp 0 → **128**, `iso_sum` wt_zp 128 → **0**, `iso_bias` wt_zp 129 → **−1** |
| **float surface** | ~`544`+ | **the dequantised weights** (`wt_sc·(q−zp)`), float32, in the HW-tiled weight order | `iso_sum` surface = the model's **±100** values; `idg_A` distinct vals top out at **25 = max(ky·5+kx+1)**; `idg_B` at **16 = max(ic+1)**; `idg_C` encodes **oc+1** |

So the "mystery floats" at `0x5024` are **a second copy of the weights**, dequantised to float32 — the
hardware reads the weights twice (int8 to the CMAC at `0x1110`, float32 to the SDP at `0x5024`). Mesa
writes the int8 copy but leaves the float copy **zero**, which is why every asymmetric layer saturates.

**Mesa's two concrete bugs in `rkt_fill_biases` (RK3576 path):**
1. **Layout.** It writes `[8×i32 A | 8×i16 B | 8×i16 C]` per 64-byte group; the hardware wants a
   *contiguous* `int32[128]` A then a *single* scalar B. The two layouts only coincide for `oc<8`;
   every channel from 8 up reads A out of the wrong slot.
2. **Empty float surface.** The `+0x100` "X2 pad" left zero is actually the dequantised-weight array
   the SDP requires.

The **A-term math** Mesa already has (`0x80*(sw+bias)`) is the right shape — confirmed `R²=1.0` on
`iso_sum`. (The standalone per-**tensor** `conv2d.tflite` capture, `vendor-bias.bin`, is 20800 B with a
*different* shape — an extra `int32[128]` where the per-channel buffer has the scalar B — so the
per-tensor and per-axis encoders differ; MobileNet is per-axis, so the per-channel format above is the
one to implement.) The float surface decodes (confirmed two clean independent ways — `idg_A` is the kernel ramp
`1,2,…,25`; `iso_sum` is the model's `±100` in clean **25-wide (= 5×5 kernel)** blocks; both put
**kernel position innermost**) as the **dequantised weights**. The layout is **fixed-position** (same
offsets for the same conv shape, not a content-sized stream): `A[128]` int32, the `B` scalar + pad,
then a tiled weight region with a **consistent ~124-float dense block** at the same offset in every
capture (idx 256…379), a sparse `....wwww`-period-16 (= `ic`) preamble before it, and a trailing
sparse region. (An earlier "the block grows with the values → compression" read was a measurement
artifact — `iso_sum`'s `±100` simply fills the preamble's otherwise-sparse slots, it is the same
fixed layout.) **Open:** which `(oc,ic,ky,kx)` maps to each slot of that tiled region — the per-axis
order. `idg_B`/`idg_C` read anomalously (values 79.. / 133.. past the `ic+1`/`oc+1` range) so they do
*not* give the `ic`/`oc` order cleanly (possibly stale captures); the tiling has to come from the
NVDLA feature-tile definition or a board write-back test (Mesa controls the `0x5024` base, so a
candidate dense kernel-inner layout can be emitted and checked for de-saturation).

## 2026-06-23 — Harness validated faithful; the bug is the geometry/config, not the data

Two results this day, both first-hand (one on-board, one straight from the deployed source):

**1. `replay_mesa` is a FAITHFUL reproduction (board-validated).** Booted an image whose only
NPU job was the *real* Mesa Teflon `conv2d.tflite` (so the kernel's `audit_arm` cnalive fires on
the genuine Mesa payload, not the replay). The real Mesa path gives the *same* signature as the
`replay_mesa` reconstruction:
- `OUT: distinct=2 (min=7f max=80)` — degenerate, identical to the replay.
- `cnalive: ds0_first=-1`, `CNA G0_DS0=0 G1_DS0=0` — same as the replay.
- And crucially the **operand BOs are all real**: `in distinct=251`, `wt distinct=199`,
  `bia distinct=127`. The inputs/weights/bias are non-degenerate; only the **output** collapses.

So this is **not** a data-degeneracy bug (the coefficients reach DRAM intact) and the `replay_mesa`
harness can be trusted. The defect is in the **command stream / geometry**, surfacing as the engine
producing a constant.

**2. The conv shape is confirmed, and Mesa's geometry encoding for it does not match the vendor.**
`conv2d.tflite` = input `[1,80,80,16]`, weights `[128,5,5,16]`, output `[1,40,40,128]`, 5×5,
**stride 2**. The vendor capture is the *same* op (its BO sizes match exactly: input 80·80·16 =
102400, output 40·40·128 = 204800, weights 128·5·5·16 = 51200), and it dispatches it as **3–4
tasks** split by output-channel.

Mesa's `rkt_task.c` / `rkt_regcmd.c` compute the CNA geometry with **shape-specific hand-tuned
constants** (`input_width==8`, `input_channels==32 && input_width==80`, `input_width==40 &&
input_channels_real==40`, `input_surface_stride=112`, the `input_width>=112 && stride==1`
row-window path, plus a block of `emit_raw()` magic values). This generic `[1,80,80,16]` stride-2
conv matches **none** of those special cases, so it falls to the generic path — and the generic
path emits geometry that diverges from the vendor. Concretely, the deployed source emits
`CNA_DATA_SIZE0 = DATAIN_WIDTH(80)|DATAIN_HEIGHT(80) = 0x00500050`, whereas the vendor capture has
`0x00000190` (W=0, H=400) for the same op. The whole rocket geometry encoder is tuned per-shape and
is incomplete for shapes outside the hand-fitted set — that is the bug class.

**The vendor's CNA geometry decodes to GEMM dimensions (conv-as-matmul).** Matching the
vendor capture's CNA registers to arithmetic of the known conv shape, four fields land exactly:
`DATA_SIZE0` height `0x190 = 400 = ic·kh·kw = 16·5·5` (the **K** / contraction dim — the
im2col gather depth), `DATA_SIZE1` channel `0x7f = 127 = oc-1 = 128-1` (the **N** dim),
`DATA_SIZE2` hi `0x640 = 1600 = ow·oh = 40·40` (the **M** dim), `DATA_SIZE2` lo `0x0f = 15 = ic-1`
and `DATA_SIZE3` `0x4f = 79 = iw-1`. So the RK3576 CNA wants the conv **folded into a GEMM**
(M=1600, N=128, K=400), not the raw spatial `[W,H,C]`. (One field, `DATA_SIZE1` channel_real
`0x404 = 1028`, does not decode cleanly yet.) A 1×1 kernel makes the folding trivial (K=ic), which
is why the pointwise/depthwise MobileNet layers limp by while this 5×5 conv exposes it.

**A regression, and a residual.** An *earlier* Mesa (the stale dump) emitted the **folded** values
(`DATA_SIZE0=0x190`, `DATA_SIZE2=0x0640000f`, `DATA_SIZE3=0x004f004f` — all = vendor; only
channel_real differed, 514 vs 1028). The **current** deployed Mesa has **regressed** to raw spatial
dims (`DATA_SIZE0=0x00500050`, `DATA_SIZE1=0x000f0010`, `DATA_SIZE3=0x640`). So restoring the folded
geometry is a concrete, necessary fix for the current tree. It may not be *sufficient*: a
full-config `replay_mesa` test on the old (folded) dump — op_en/pad stripped, `0x1018/0x1024`,
the OUT_CVT requant and CBUF all patched to the vendor — still saturated (distinct=2, ds0_first=-1).
That test left exactly one config register un-patched: **`DMA_CON2` (0x1080) `SURF_STRIDE`**
(mesa `0x00000101` vs vendor `0x02020101`). So the residual is either that surface stride or the
submit structure itself — the single decisive experiment is `replay_mesa` full-config **plus**
`0x1080 → vendor`.

**`DMA_CON2` patched → still saturates (2026-06-23). The regcmd is now FULLY ruled out.**
Ran exactly that: `replay_mesa` with op_en/pad stripped and `0x1018/0x1024/0x1040/0x40ac/0x40b0/
0x40b4/0x1080` all → vendor — i.e. the command stream byte-identical to the vendor's task0 (only the
address registers differ, pointing at the replay's own BOs). Result: `OUT distinct=2`, `ds0_first=-1`,
live `DATA_SIZE0=0` — **unchanged**. Meanwhile `replay_rocket` (the vendor's *payload* — same regcmd
**and** the vendor's weights/bias BOs — through the same rocket UABI) *computes* (distinct=254). So:

> **The conv2d defect is NOT in the command stream.** A vendor-byte-identical regcmd, submitted by
> Mesa's path, still produces the constant output. The remaining difference between the computing
> `replay_rocket` and the failing `replay_mesa` is the **payload data and submit path**: the
> coefficient BO contents/layout (Mesa packs weights as 204800 B per-tensor; the vendor's regcmd
> expects its own 51200 B per-channel packing at `0x1110`, and the per-channel requant A/B/C buffer
> at `0x5020`/`0x5024`), and possibly the task tiling (Mesa dispatches one task; the vendor tiles
> 3–4). The 300 KB scratch BO (bo02) is **not** referenced by any address register, so it is ruled
> out. Next decisive split: `replay_mesa` + vendor regcmd + **vendor weights + vendor bias** — if it
> computes, the bug is purely Mesa's coefficient encoding (`rkt_coefs.c`); if it still saturates, the
> bug is the submit/tiling path (`rkt_task.c`/`rkt_ml.c`).

**RESOLVED (2026-06-23): the bug is the COEFFICIENT DATA. `replay_mesa` + vendor regcmd +
vendor weights + vendor bias → COMPUTES** (`OUT distinct=98, nonzero=202859/204800`, head
`0a 0b 0b 05` — a real feature map). The only change from the saturating run was swapping Mesa's
weights/bias BOs for the vendor's. Therefore:

> The conv2d defect is **entirely in Mesa's coefficient (weights + bias/requant) encoding**
> (`rkt_coefs.c`). The command stream is fine (vendor regcmd used either way), and **Mesa's single-task
> submit path is fine** — it computes the whole conv (99% nonzero) when fed the vendor's coefficients.
>
> Two artifacts are now retired: (1) `ds0_first=-1` is a **timing artifact**, not a geometry-latch
> failure — this run *computed* with `ds0_first=-1` (the single task finishes before the kernel's
> 4000-sample poll catches `DATA_SIZE0` non-zero); trust the OUTPUT distinct, not `ds0_first`.
> (2) the "geometry not latching / conv0 wall" framing is moot — geometry latches fine; the engine
> was running on mis-encoded coefficients.

Next: isolate **weights vs bias/requant** (one swap at a time). My own note added to the driver
(`rkt_ml.c:348-364`) flags the per-channel requant buffer as the suspect/TODO, and the weight
*packing order* was already shown to match the vendor — so the bias/requant A·B·C buffer
(`0x5020`/`0x5024`, per-tensor in Mesa vs per-channel in the vendor) is the leading candidate.

**ISOLATED to the BIAS/REQUANT buffer (2026-06-23).** `replay_mesa` with the full vendor
regcmd and **Mesa's own weights** but the **vendor bias buffer** (`MESA_BIAS` = bo1[51200:72000])
→ **COMPUTES, `OUT distinct=252`** (an even cleaner feature map than the all-vendor run). So:

> Mesa's **weight encoding is correct** (packing order + quantization both fine); the entire
> conv2d defect is the **per-channel requant / bias buffer** at the weight-BO tail (regcmd
> `0x5020` → A·B·C, `0x5024` → the second per-channel array). Mesa writes it per-tensor; the
> vendor writes it per-channel. Swapping *only* that buffer to the vendor's makes the conv
> compute. **This is exactly the per-channel-requant TODO I noted in `rkt_ml.c:348-364`** — upstream
> doesn't attempt it (it gates per-axis quant out as "not supported"); this note is my own. The fix
> lives in `rkt_coefs.c` (the bias/requant emit), and nothing else needs to change.

The remaining work is purely to decode the vendor's per-channel requant buffer
(`vendor-bias.bin` = bo1[51200:72000], now a *known-good* reference because it computes) into a
formula over the conv's quant params + per-output-channel weight sums, and emit it from
`rkt_coefs.c`.

**The "A" term: formula structure confirmed; the scale is the remaining piece (2026-06-23).**
Decoded the vendor 0x5020 buffer as the `[8×i32 A | 8×i16 B | 8×i16 C]`-per-8-oc layout (Mesa's
assumed layout — confirmed; a flat layout decodes to garbage). Offline-fit the vendor's per-channel
`A` against the conv quantities: **`vendor_A = -M · (bias_q - in_zp·sw)`, k = -1.3155 ≈ -M (=-1.299),
R² = 0.991** over all 128 channels (`M = in_sc·wt_sc/out_sc`). So the per-channel offset is
**structurally `A ∝ (in_zp·sw - bias_q)`** — Mesa's `A = 0x80·(sw + bias)` has the wrong sign on the
weight-sum term, omits the `in_zp` factor, and is scaled by `0x80` instead of `M`. (`B`,`C`, and the
0x5024 float array did *not* fit the per-tensor quantities, R²<0.07 — they carry the vendor's
**per-channel weight re-quantization**, which a per-tensor Mesa path doesn't need to reproduce.)

The blocker is the **scale/shift**, not the formula: a board test that fixed only `A` (keeping
Mesa's `OUT_CVT` shift=14) saturated *identically to baseline* (`80 80 7f 7f`) — at shift=14 the
output clips regardless of `A`, because the vendor runs the whole SDP `2^12` hotter (shift=26 vs 14;
its `A` is pre-multiplied by `M`, i.e. `vendor_A = M·(in_zp·sw - bias)` in output units, brought back
down by the larger shift). So the correct Mesa emit is `A = in_zp·sw - bias_q` with the SDP scaled
the vendor's way (shift≈26 and the matching `A`/`B`/`C` scale), **not** Mesa's current shift=14 +
`0x80·A`. Pinning the exact shift/scale constants is the last step (needs the SDP scale semantics or
a couple of focused board runs).

**The exact fixed-point scale is NOT cleanly derivable from arithmetic (2026-06-23).** Tested the
corrected-sign `A = in_zp·sw - bias` (constant `B = 0x80-wt_zp`, `C = 0x4000`, `0x5024` zeroed) at
both shifts: shift=14 saturated *identically to baseline* (`distinct=2`, `7f 7f 80 80`) — at that
scale the `A` buffer has no effect at all, the overall output simply clips; shift=26 moved it only
from 2→3 distinct (still `7f 7f 80 80`, not a feature map). The vendor's buffer computes at shift=26
because of its **per-channel `B`, `C`, and the `0x5024` float array** — which carry the SDP scale,
and which I set to constants/zeros. Those did *not* fit the per-tensor quantities (R²<0.07), and the
fixed-point datapath (how `A`·`B`·`C`·`BS_MUL`·`OUT_CVT` combine bit-for-bit) is not recoverable
from the known-good buffer + the quant params alone — every fixed-point model tried (shift=14 direct,
shift=26 raw) was wrong on the board. So the *structure* is settled (bug = the bias/requant buffer;
`A ∝ in_zp·sw - bias`, R²=0.99) and is upstreamable as-is (this is the per-channel-requant TODO I
left in `rkt_ml.c`; upstream gates per-axis out rather than attempting it), but the
exact scale constants need the RK3576 SDP datapath spec (the per-channel `BS_MUL`/`OUT_CVT` fixed-point
semantics), not further blind arithmetic. That is the clean handoff line.

**The requant is TWO per-channel BS surfaces; Mesa leaves the second one zero (2026-06-23).**
The DPU bias is read by `DPU_RDMA` from *two* surfaces: `0x5020` (`RDMA_BS_BASE_ADDR`) holds the
`[A|B|C]` int table, and `0x5024` (the "second buffer") holds a per-channel **float32** array. Both
are essential — board isolation, vendor weights, vendor regcmd, shift=26:

- `A` alone (vendor's exact `A`, `B`/`C`/floats zeroed) → `distinct=1` (constant = the OUT_CVT
  offset). The bias-add alone carries nothing.
- `A`/`B`/`C` kept, the `0x5024` floats zeroed → `distinct=2` (degenerate).
- The full vendor buffer (both surfaces) → `distinct=252` (computes).

So the `0x5024` float surface is required, and **Mesa never writes it**: `rkt_fill_biases` allocates
`groups*64 + 0x100` and points `0x5024` at `bias_addr + 0x400`, which lands in the zeroed `0x100`
pad. That zero second-surface is a concrete part of the bug. The float array decodes to a per-channel
table (`float[0] = -wt_sc`, then 128 varied per-channel floats — *not* the per-channel weight scales,
not any clean function of the per-tensor quant params). It is produced by the vendor toolkit's
per-channel quantiser, which lives in the compiled `librknnc.so` (rknn-toolkit2 2.3.2) — not in
readable Python and not recoverable by swapping/fitting (proven exhaustively: A-alone, A+B/C-no-float,
and every fixed-point model all fail on the board). 

**Net:** the conv2d defect is fully cornered — it is the per-channel SDP requant, two BS surfaces
(`0x5020` int `[A|B|C]` + `0x5024` float), of which Mesa writes only the first and gets the `A`-term
wrong. The `A`-term is solved (`A ∝ in_zp·sw - bias`, R²=0.99). The remaining per-channel `B`/`C` +
float surface are the vendor toolkit's per-channel re-quantisation and need the RK3576 SDP datapath
semantics (how the int and float surfaces combine in the converter) — i.e. the per-channel requant
TODO I noted in `rkt_ml.c` (upstream doesn't attempt it), now with the exact surfaces and the A-term
pinned. That is the real handoff: a feature
(per-channel requant + the second BS surface), not a value left to guess.

**Honest caveat / next step.** The earlier register-level diff used a *stale* `mesa-regcmd` dump
(captured from a pre-2026-06-16 Mesa; the deployed lib is 2026-06-19 and its geometry code differs,
e.g. `0x1018` is now hard-coded to `0x40000404`). To pin the exact current divergence, the next
board run must take a **fresh** regcmd dump from the *deployed* Mesa and diff it against the vendor
capture (the only fixed reference), then trace each divergent CNA register back to the
`rkt_task.c` computation. Single submit, low crash risk.

## Symptom (precise)

- Full graph runs end-to-end: no IOMMU fault, no PC timeout (on the GPLL clock), every layer
  reads its own real feature data from DRAM (bandwidth counters confirm the CNA pulls the whole
  input + weights into the CBUF).
- The **CMAC reads ~0 out of the (correctly loaded) CBUF**: `core[wt_rd=0, dt_rd≈0]`, writes a
  degenerate output (`dt_wr` = a fraction of the full volume). conv0 output is `distinct=2`
  (min=0x7f, max=0x80) — i.e. ±(one constant), not a feature map.
- No per-unit completion ever fires (`INTERRUPT_RAW_STATUS` FEAT/WT/CSC/CORE/DPU all 0); only the
  PC asserts done, and it does so ~1 µs after OP_EN (`samples=1`) — a hollow, instant "done".

### The whole bug, pinned to one counter (2026-06-21)

A counter-level read of conv0 isolates it past any doubt — everything upstream of the CMAC weight
read is confirmed correct, and the failure is a single zero:

- `top[dt_rd=9408×16 = 150528]` = the **full** 224×224×3 input is DMA'd from DRAM into the CBUF.
- `top[wt_rd=96×16 = 1536]` = the conv0 weights are DMA'd into the CBUF, in the **RK3576-specific
  first-conv (ARGB) pack** (ky-major, 1536 B — board-derived; the RK3588 pack is a known wrong path).
- The CBUF SRAM readback (`@0x3fe80000`) shows the data region staged (`@0x0 d164/nz717`) and the
  weight blocks the vendor's `cache_sgt` defines (`@0xe0000/0xf0000`) holding dense packed weights.
- `0x3018=0x10000081` (first-conv mode 0x81), the per-channel weight zero-points (`0x1054/58/5c =
  0xffffff80`) and every CNA/CORE weight register are byte-identical to the vendor; the executers
  engage (`exec_ever=0xf`).
- **And still `core wt_rd = 0`** — the CMAC reads none of the loaded, correctly-formatted weights.
  Weightless MACs → zero-point → the DPU writes a fixed 2-channel (`dt_wr=25088`) degenerate output,
  which starves every downstream layer (they then read `top[…=0]` and repeat the same 25088).

So the bug is **not** staging, format, banks, mode, or any command-stream value — it is solely the
CNA-weight-subunit → CMAC weight-read handoff: the weight-load-done that should kick the CMAC's CBUF
read never asserts (matching the dead WT/CSC interrupt). One latch, no register window.

### Single-op isolation (2026-06-21, Tomeu's method) — 2 of 3 suspects cleared

Reproduced on the **simplest standalone conv** (Mesa's own `conv2d.tflite`, 5x5, 16→128, nothing to
do with mobilenet): NPU output `distinct=2`, CPU output a real feature map. So the bug is **per-op,
not whole-graph**, and it affects a **normal** conv, not just the first-conv. Tomeu's three suspects:

- **coefficients BO — ruled out.** `ROCKET_DEBUG=dump_bos`: Mesa's encoded weights are varied
  (distinct=241), same value range as the tflite, just NVDLA-repacked (51200→204800 + padding).
- **input BO — ruled out.** PRE/POST CBUF SRAM dump: the input feature ramp stages in cleanly
  (`@0x0` goes from garbage to the known ramp `80 81 82 …`).
- **a kernel-side write — the remaining suspect.** Weights are DMA'd from DRAM (`top wt_rd=3200`) but
  the weight blocks (`@0xe0000/@0xf0000`) read **byte-identical PRE and POST** and `core wt_rd=0`:
  the weights are read but never deposited into the CBUF weight bank.

Tried staging weights into the on-chip SRAM + repointing the CNA weight source (0x1110) to it (fix
#1 at an arbitrary IOVA, fix #2 at the vendor's exact NBUF window 0xffff8000) — neither moved
`core wt_rd`, so the weight *source location* is not the lever. The one structural gap vs the vendor:
it places all BOs (incl. weights) in the on-chip **NBUF** (the `rk3576_cache_sgt_init` setup rocket
lacks); rocket uses DRAM. Open question to Tomeu (flipper #55): what arms the CNA weight-load deposit
into the CBUF on RK3576 — the NBUF residency, or a kernel register write.

### conv2d payload diff: operands vs Mesa (2026-06-21, Tomeu's ask)

Dumped the full BO payload (weights/input/bias/output) the **vendor** stack hands the hardware for a
standalone 16→128 5×5 conv and laid it next to **Mesa's**, both running the *same* conv (the vendor
`.rknn` rebuilt from Mesa's own `conv2d.tflite` weights) fed the *same* ramp input. Vendor side:
instrumented `rknpu_job.c` to translate the regcmd's BO addresses (0x1088 input / 0x1110 weights /
0x4018 output / 0x5020 bias) through the IOMMU and print the bytes; Mesa side: `ROCKET_DEBUG=dump_bos`.
Both emitted over the serial console as text (`rknpu cap:` / `mesa cap:`) and diffed with
`vendor-capture/diff_payload.py`. Mechanism check: the vendor **input** BO reads back the exact ramp
fed → the dump reads the right memory, not neighbouring garbage.

- **weights** — dense and varied on both (~99% nonzero; distinct 256 vendor / 221 mesa). Mesa's
  coefficient BO is **not** degenerate.
- **input** — the same ramp on both (staging equivalent).
- **bias** — populated on both.
- **output** — the only divergent buffer: Mesa's computed output is degenerate (`distinct=2`). The
  vendor output was caught at submit (pre-compute), so the *computed* results aren't compared here.

What it establishes / what it does **not**: it rules out "Mesa hands the engine empty or zeroed
operands" — they are well-formed. It does **not** separate a weight **packing-order** defect (right
values, wrong layout → the CMAC reads them as noise) from a pure **execution** defect: the two
toolchains quantize independently, so the weight bytes differ everywhere and the packing *order* can't
be byte-compared. Both defects produce the identical signature (dense weight BO + degenerate output).
Consistent with the `core wt_rd=0` CBUF→CMAC localization, **not proof** of it. Open lever: get the
vendor toolkit to ingest the exact tflite int8 weights (it rejects `load_tflite` on arm64) for a
byte-identical layout diff — handed back to Tomeu.

### Faithful payload replay through the vendor UABI — it computes (2026-06-22)

The diff above caught the vendor output *pre-compute*. The fix: capture librknnrt's **entire**
submission and replay those same bytes through the vendor `rknpu` DRM render node, so the *computed*
result is observable. An `LD_PRELOAD` shim (`vendor-capture/capture.c`) records every BO librknnrt
creates and, on the first `SUBMIT`, maps each itself and dumps the content + the raw submit struct.
The standalone conv turns out to be **5 BOs over 3 tiled tasks** (a 4 KiB task-array, a 76 KiB
weights+bias+3-regcmd BO, a 300 KiB scratch, the input, the output), not the single regcmd a naive
replay assumed. `replay.c` re-creates those BOs (same order/size → same deterministic IOVAs, so the
address-remap is a no-op as the first job), loads the bytes, and submits.

Result: the replayed conv produces a **non-degenerate output** — `distinct=254`, `202547 / 204800`
nonzero — written by the NPU into an output buffer the capture confirms was **all-zero** at submit.
This is the first time the captured payload has computed a real result on this bench, and the
control Tomeu's method needs: **the captured bytes + the vendor kernel are sound** — the payload was
never the defect.

The decisive variable was **not** in any BO or the regcmd — it was the submit struct's
`subcore_task[5]` array, which an ioctl *type* trace can't see. librknnrt splits the 3 tiled tasks
across subcore slots — `subcore[0]={start 0, num 1}`, `[1]={1,1}`, `[2]={-1,1}` (`task_counter=0`,
`core_mask=0` AUTO). A hand-built submit that instead put all three on one slot (`subcore0={0,3}`)
ran **task 0 then stalled task 0→1** — `INT_RAW_STATUS=0x30000000`, never the `0x300` the kernel
waits for — i.e. it reproduces the long-standing "PC stalls task0→1" wall exactly. So that wall is a
**dispatch artifact** (one multi-task dispatch the PC won't iterate), not the payload: split into
single-task dispatches and the identical bytes compute. Soft-reset (vendor never issues one) and an
explicit `POWER_ON` (the submit ioctl already `power_get`s via its wrapper macro) were both ruled out
along the way. Tooling tracked in `replay/` + `vendor-capture/`.

**Next:** replay the *same* captured bytes through the **rocket** UABI (`/dev/accel/accel0`). If it
also computes, the rocket kernel is sound and the divergence is in Mesa's payload generation; if it
diverges on identical bytes, the defect is isolated to the rocket kernel driver. The mainline rocket
job model ("all tasks in one job run sequentially on the same core") vs the vendor's per-task subcore
split is the lead to test.

### Same bytes through the rocket UABI — it computes too; the bug is Mesa's payload (2026-06-22)

`replay_rocket.c` re-creates the four data BOs through the rocket UABI (`CREATE_BO` returns each
one's rocket-assigned NPU IOVA), remaps every captured IOVA the regcmd references to those new
addresses (the cross-UABI step the same-IOVA vendor replay didn't need), and submits each tiled task
as its own one-task job (`DRM_ROCKET_SUBMIT`, the vendor's per-subcore split). The rocket kernel
points the PC at the task's regcmd and pulses `OPERATION_ENABLE` itself, so the vendor regcmd (which
folds `op_en` into the submit header rather than appending the broadcast entry Mesa does) runs as-is.

Result: rocket computes the captured payload — output `distinct=254`, `202547/204800` nonzero, head
`07 0e 09 04`, **byte-statistics identical to the rknn replay**, into a verified-zero output buffer.
And in the *same boot*, Mesa's own conv on the same NPU stays degenerate (`distinct=2`). Repeated
under both firmwares to kill the BL31/OP-TEE variable:

| payload \ SPI firmware | vendor (Rockchip TF-A + OP-TEE) | mainline (TF-A v2.14.0, no OP-TEE) |
|---|---|---|
| **vendor** (replay_rocket, captured bytes) | COMPUTES | COMPUTES |
| **Mesa** (its own encoded payload)         | degenerate | degenerate |

The captured bytes compute through *both* UABIs under *both* firmwares; Mesa's payload degenerates
under both. So the defect is **not** the rocket kernel, **not** the hardware/CBUF, **not** the
firmware — it is isolated to **what Mesa encodes**: the coefficient (weights+bias) BO. (One aside:
the rocket multi-task-per-job path NULL-derefs — `replay_rocket` runs one task per job, the shape
Mesa uses anyway.) `replay_rocket.c` tracked in `replay/`.

### It is per-channel weight quantization, NOT packing order (2026-06-22, correction)

A first read of the above guessed the coefficient defect was the weight **packing order**. Decoding
the layout proved that wrong. Position-encoded convs (`vendor-capture/gen_id_generic.py`: three
16→128 5×5 models with `w = ky*5+kx+1` / `ic+1` / `oc+1`) were converted to `.rknn`; the vendor
toolkit packs the weights into the `.rknn` at build time, so the packed buffer is extractable on the
**host** (the min-distinct 51200-byte window — no board flash). Decoded nesting, outer→inner:
`oc1(/32) → ky → kx → oc2(0..31) → ic` — which **matches Mesa's generic `rkt_fill_weights` 100%**.
Packing order is not the bug.

The real difference is the **quantization**. `conv2d_rk3576.rknn` is built `do_quantization=False`, so
it carries the *same* source int8 weights as Mesa; byte-comparing the vendor's packed weights against
the source (in the now-known order) shows each output channel is a **per-oc affine** of the source —
`|corr| = 1.000` for all 128 channels, slopes spanning **1.07–1.67×**. The vendor quantizes weights
**per output channel**; Mesa uses one **per-tensor** `weight_tensor->scale` (`rkt_regcmd.c:334` → a
single OUT_CVT scale/shift at DPU `0x40b0`/`0x40b4`; the `rkt_coefs.c:411` hardcoded-scale list is
the non-RK3576 path). The vendor's SDP requant is itself **per-channel**: regcmd `0x5020` →
`bo01[51200:52224]` is a 1024-byte struct of 16 groups ×`[8×i32 A | 8×i16 B | 8×i16 C]`, and A, B, C
all vary per channel (B correlates −0.98 with the per-oc stored-weight sum; A carries a scale term
plus a bias term). Mesa's RK3576 bias path treats B as the per-**layer** constant `0x80 − wt_zp`.

So: **the RK3576 NPU expects per-output-channel weight quantization (and a per-channel SDP requant
buffer); Mesa emits per-tensor.** This is consistent with — and likely the same root cause as — conv0's
"~2 of 32 channels" channel-bank truncation: per-tensor quant scales every channel by the global max,
crushing the small-magnitude channels toward zero. Open: the exact A/B/C formulas (per-channel
scale-mult / shift / zero-point compensation) — to be cracked with single-variable isolation captures
(vary bias-only / scale-only / zp-only per channel, extract from the `.rknn`, fit), then implement
per-channel weight quant + the per-channel requant buffer in Mesa. Tooling:
`vendor-capture/{gen_id_generic,gen_id_bias,decode_generic,abc_locate,convert_onnx_pt}.py`.

### Bisection in a controllable harness: conv2d is the geometry-latch wall, and the in-stream op_en blocks the latch (2026-06-23)

The per-channel requant above is real for the per-**axis** MobileNet layers, but it is a red herring
for the standalone `conv2d` test: that `.tflite` is per-**tensor** (weights scale 3.912/zp 133, output
scale 0.0235/**zp 0**), and Mesa's requant (OUT_CVT shift 14, out_zp 0) is *correct* for it — the vendor's
shift 26 / zp 137 is just the vendor toolkit's own per-channel re-quantization, a different valid scheme.
What actually fails conv2d was found by reproducing it in a controllable harness rather than by
reasoning: `replay/replay_mesa.c` feeds Mesa's own dumped regcmd/weights/biases back through the rocket
UABI as one task (re-pointing the address regs), with env knobs to swap a single component for the
vendor's. Baseline reproduced the grey (`distinct=2`); swapping the **requant**, the **CBUF** `0x1040`,
and the **weights** each left it grey. None of the quantisation theory moved it.

It looked at first like a geometry-latch failure (the CNA ping-pong groups read the `pp_state_init`
default `DS0=0`/`DS1=0x80000000`), and an earlier draft here claimed the appended in-stream op_en
(`tgt=0x81 reg=0x08 val=0x1d`, the ENABLE_MASK, which the vendor folds into the submit instead) blocks
the latch — removing it flips `G0_DS0` `0→0x190` and `DS1` `default→0x0202007f`. **That read was a
measurement artifact and is retracted.** The `DS0`/`DS1` dump is taken *after* execution, and it
correlates perfectly with whether the engine *ran*, not whether the geometry committed: every variant
that engaged (`dt_wr=12800`) reads the default (the run consumes/resets the group), every variant that
did NOT engage (`dt_wr=0`) reads the real value (it sits un-consumed). So "geometry latched" was mostly
tracking "engine didn't run."

The less-confounded signal is the *during-execution* `cnalive` sample (`ds0_first`): the vendor
(computes) shows `ds0_first=0` (geometry present), Mesa baseline (saturates) shows `ds0_first=-1`
(geometry never present) — so Mesa baseline does genuinely run on an empty shape. Stripping op_en **and**
the 4 trailing `(0,0,0)` pad entries **and** patching `0x1018`/`0x1024` makes the regcmd's *structure*
(its set of entries) match the vendor's, and it *still* saturates (`distinct=2`, `dt_wr=12800`) when run
— so the regcmd **structure** (op_en / padding / geometry words) is not the bug. But that config did
**not** patch the OUT_CVT requant words (`0x40ac`/`0x40b0`/`0x40b4`) or CBUF `0x1040` to the vendor's, so
the regcmd was **not** byte-identical — those *values* still differ, and Mesa's `0x40b4` shift = 14 vs the
vendor's 26 is exactly the signature of a requant run **~2^12 too hot → clamp to 0/255 = the saturation
seen**. So the live suspects are now (1) the **OUT_CVT requant values** in the regcmd, and (2) the
**coefficient data** (weights/bias) — reviving the requant/bias direction the per-tensor argument had set
aside; the geometry/op_en/structure path is closed. (Also learned: the 4 trailing pad entries are not
junk — with op_en removed they buy ping-pong handoff time.) **Decisive next:** `replay_mesa` with op_en+pad
stripped **and** the OUT_CVT (`0x40ac=9`/`0x40b0=0x5d58`/`0x40b4=26`) patched to the vendor's — does the
saturation clear? then swap the weights/bias. (Capture `cnalive ds0_first` alongside.) (The instrumented
rocket kernel is fragile — a `drm_mm_takedown` NULL-deref crashes BO cleanup after ~2–3 submits, an
invalid OP_EN wedges the NPU — so each boot yields one or two submits before a power-cycle; key variant
first.)

## Confirmed byte-identical to the vendor

Verified on the board with an automated register-by-register diff against a live vendor capture
(instrumented `rknpu`, real IOMMU addresses):

- **conv0 regcmd**: 138/138 non-address CNA/CORE/DPU/RDMA entries match. The only delta is the
  broadcast `op_en` word rocket appends (`tgt=0x81 reg=0x08 val=0x1d`) where the vendor folds the
  same value into its submit header `enable_mask`.
- **Kernel submit** matches `rknpu_job_subcore_commit_pc` register-for-register: `PC_DATA_ADDR`,
  `PC_DATA_AMOUNT` (same formula → 71), `INT_MASK`/`INT_CLEAR` = 0x300, `PC_TASK_CONTROL` =
  `(0x7<<16)|1`, `PC_DMA_BASE` = 0, the `OP_EN` 1→0 pulse, and the `PC_DATA_ADDR=1` pre-write.
- CBUF geometry (16 banks × 512 × 128 B = 1 MiB), `state_init` (0x1004/0x1024/0x1e), the full
  soft-reset (srst_a + both CBUF resets) + IOMMU re-attach, the clocks-on set — all match.

## Ruled out (each tested on hardware)

| Hypothesis | Result |
|---|---|
| regcmd content / values | byte-identical to vendor (above) |
| submit/kick sequence | identical to `commit_pc` |
| ping-pong producer/consumer group mismatch | swept `geom_both` (geometry into BOTH groups) + cpu_replay + per-job pp_state_init + per-job CBUF reset + fixed S_POINTER, 14 combinations — all degenerate |
| op_en mechanism / broadcast value (0x1d vs 0x7f) | no change |
| dual power domain (PD_NPU0 + PD_NPU1) | added multi-PD attach (`dev_pm_domain_attach_list`) — no change |
| NPU_GRF URGENT QoS | set sel=1 — no change |
| DDR contention | 6-core hog + urgent — no change |
| readback-too-early / cache coherency | dual-path (cached vs MEMREMAP_WC) readback; delay — no change |
| IOMMU faults / stale TLB | none; rk_iommu has no `.flush_iotlb_all` |
| clock **rate** (GPLL 198 MHz … 786 MHz) | no change |
| clock **source** PVTPLL (see below) | makes it worse — 0 jobs complete |
| **submit-time timing race** (pure busy-wait 1 µs–1 ms before OP_EN, swept ×20 runs) | **no change** — conv0 writes exactly 2 of 32 channels (`core dt_wr`=25088) every run, every delay |
| per-job ping-pong pointer advance (`double_kick` warmup pulse) | no change — same flat 2 channels |

## Clock-ID finding (useful, upstreamable) and the PVTPLL dead end

The vendor sources the compute clock `CLK_RKNN_DSU0` via **SCMI** (TF-A → PVTPLL); mainline routes
it via `&cru` (fixed PLLs). `aclk_rknn0` and `aclk_rknn_cbuf` are bare gates off DSU0, so CBUF and
compute share one clock — they cannot be decoupled, on either driver.

Routing rocket's `npu` clock to `<&scmi_clk CLK_RKNN_DSU0>` silently no-ops: **the kernel CRU
binding numbers the clock 232, but our TF-A `clock_table` keys it at 238.** `<&scmi_clk 238>` is
settable (rate reads back). But on PVTPLL — correct index, correct rate, OPP voltage raised first
(800 MHz needs 800 mV), rate-set moved after the soft-reset — the NPU completes **0 jobs** (~83
`drm_sched` timeouts / 90 s). PVTPLL needs the full vendor stack (per-chip leakage cal via nvmem +
OPP/devfreq governor) to be a usable clock; the GPLL path at least runs and computes its wrong
answer. The clock theory (that the failure is a timing race) was never testable — PVTPLL never ran
cleanly. Reverted to GPLL.

## Localization / the open question

The gap is the on-chip **CBUF → CMAC** hand-off, the one place with no register window: the CNA
stages the full operands in (bandwidth counters prove it), the vendor's identical command stream
then computes, and rocket's identical stream reads zero. Nothing pollable distinguishes the two.

The truncation is **deterministic within a power cycle**, not a race: a 20-run × 5-point sweep of a
pure pre-kick busy-wait (1 µs–1 ms) and a ping-pong pointer advance both left conv0 at exactly 2 of
32 output channels every run (0 full-channel results in ~1000 jobs). A submit-time read-too-early or
ping-pong race would vary and respond to delay; this does neither — the cut is locked *before* the
job, in the CBUF power-up/reset state, which reads as a channel-bank truncation rather than a timing
race. (An external NVDLA bring-up engineer independently called this "a race below observability";
the sweep is the clean refutation of that for the submit window.)

**What would crack it:** an NVDLA-derived microarchitecture reference for the RK3576 CBUF/CMAC, or
a register-write trace from a *working* RK3588 rocket run to diff the execution (not just the
command stream) against, or silicon-level visibility. This is past what black-box probing from the
mainline driver + DT + as-flashed firmware can reach.

A sister-chip bring-up (RK3568, mainline rocket) is stuck at the same class of wall, a stage
earlier (engage), which suggests one real SoC-family issue, not ten imagined ones —
see https://github.com/gahingwoo/linux-rk3576-npu/issues/1.
