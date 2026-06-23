# RK3576 NPU (rocket + Mesa Teflon) — conv0 zero-output: complete findings

**Status:** platform bring-up is solid; **compute is wrong.** Every convolution computes to
the quantized zero-point. The wall is below the register surface and is handed upstream here.

- HW: Radxa ROCK 4D (RK3576). Stack: mainline **rocket** accel driver + **Mesa Teflon**.
- Reference: vendor `rknpu` + RKNN runtime runs the same MobileNetV1 correctly on the same board.
- CPU ref: Top-1 653 / conf 0.887. NPU: Top-1 0, output all zero-point.

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
