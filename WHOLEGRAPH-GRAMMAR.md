# RK3576 whole-graph regcmd grammar — vendor vs mesa, and the Phase-B go/no-go (2026-07-05)

Question: does mesa's RK3576 regcmd stream LACK a per-task self-iteration grammar
element the vendor emits (GO — implement in mesa), or does it already carry it and
the PC wedges anyway (NO-GO — internal, close #1, go RTL)?

**Verdict: GO** — the vendor multi-task regcmd ends every task with a self-iteration
trailer that mesa's RK3576 whole-graph packer does NOT reproduce (it replaces the
key element). But the compile-time evidence contains a contradiction that ONE cheap
runtime capture must resolve before/with implementing. Details below.

## A1 — the vendor whole-graph grammar (decoded from vendor-toolkit .rknn)

`extract_regcmd.py` + a raw decode of the task boundary in the vendor-compiled
`.rknn` files. Each task = 139 config entries (CNA/CORE/DPU/RDMA), then a TRAILER,
then zero-pad to a uniform stride (chain: 0x480 B = 144 u64; larger tasks stride
more, e.g. run6->7 = 0x5c0). Targets: 0x0201 CNA, 0x0801 CORE, 0x1001 DPU, 0x2001
RDMA, **0x0101 PC**, 0x0041 SYNC, 0x0081 BCAST.

**Multi-LAYER chain (`chain_rk3576.rknn`, conv0->dw1->pw1->dw2), task 0 trailer:**
```
[139] PC   reg 0x10 (BASE_ADDRESS)     = 0x00000480   <- next task's regcmd addr (=stride, relative)
[140] PC   reg 0x14 (REGISTER_AMOUNTS) = 0x00000047   <- next task's fetch amount (=71 = pc_data_amount)
[141] SYNC 0x0041                      = 0
[142] BCAST 0x0081 reg 0x08 (OP_EN)    = 0x0000001d    <- broadcast operation-enable (re-fire)
[143] 0 pad
[144] next task config resumes: CNA 0x1004 = 0x0e ...
```
**Single-conv TILED models (`conv0_rk3576.rknn`, `conv2d_rk3576.rknn`, 4 tiles):**
```
[139] 0 pad
[140] PC   reg 0x14 = 0            <- next-amount 0 (no explicit next-addr; uniform tiles stride)
[141] SYNC 0x0041 = 0
[142] BCAST 0x0081 reg 0x08 = 0x1d <- SAME broadcast OP_EN, always present
[143] 0 pad
```
So: the **broadcast OP_EN (0x81/0x08 = 0x1d) is present in EVERY vendor multi-task
task**; the **PC next-pointer (0x10 addr / 0x14 amount) is populated only when the
next task is at a different address** (the multi-layer chain), and left 0 for
uniform tiles that the PC reaches by striding. The "+4 EXTRA" in the kernel's
`pc_data_amount = (regcfg_amount + 4 + scale-1)/scale - 1` is exactly this 4-entry
trailer (0x10, 0x14, SYNC, BCAST) that the PC reads past the 139 config entries.

With PC_DMA_BASE_ADDR = 0 (confirmed), the PC finds the next task from the STREAM:
the trailer re-points the PC's own fetch (0x10/0x14) and the broadcast OP_EN re-fires
it — a self-modifying next-pointer walk. NOT a descriptor array, NOT pure fixed
stride for differently-sized layers.

NOTE the single-vs-multi distinction resolves an old confusion: a **single-task**
(task_number=1) capture ends at RDMA config with NO trailer, which is why the mesa
comment says "the vendor's per-task regcmd has none." The trailer is a MULTI-TASK
feature, and it is real.

## A2 — what mesa RK3576 / RK3588 / wg_continuous emit

- **mesa fill (`rkt_regcmd.c` fill_regcmd_rk3576_normal, ~L260-270):** emits the PC
  0x10/0x14 slots ONLY if `getenv("ROCKET_NEXTPTR")` (else absent), then ALWAYS emits
  the broadcast `emit_raw(regs, 0x81, PC_OPERATION_ENABLE(0x08), 0x1d)`. It does NOT
  emit the SYNC (0x41).
- **mesa RK3588 (`rkt_ml.c` compile_operation, L310 `soc != RK3576`):** patches
  `reg_count-4` (= PC 0x10) with the next task's absolute addr and `reg_count-3`
  (= PC 0x14) with the next amount, and KEEPS the broadcast OP_EN. RK3588 does NOT go
  through the RK3576 packer (rkt_pack_graph_regcmd returns early for non-RK3576).
  **So the working RK3588 path = vendor grammar: next-pointer trailer + broadcast
  OP_EN kept.**
- **mesa RK3576 whole-graph (`rkt_ml.c` rkt_pack_graph_regcmd, L107-275) = what
  wg_continuous submits:** repacks all tasks at a uniform stride, task_number = N,
  one OP_EN, PC_DMA_BASE=0. Then, per task:
  - **REPLACES the broadcast OP_EN** (0x81/0x08) with FOUR per-unit OP_EN writes
    (CNA 0x1008, CORE 0x3008, DPU 0x4008, RDMA 0x5008) — L169-221 — on the belief
    that "the broadcast writes PC reg 0x08 = PC_OPERATION_ENABLE -> RESTARTS the PC
    each task and stalls (PC_TASK_STATUS stuck)."
  - **does NOT patch the next-pointer** (0x10/0x14) unless `ROCKET_NEXTPTR` — and even
    then the broadcast is already replaced, so 0x10/0x14 patch + per-unit OP_EN, NOT
    the vendor combo.
  - never emits the SYNC (0x41).
- **kernel wg_continuous (`rocket_job.c`):** single regcmd base + task_number = N +
  one OP_EN, PC_DMA_BASE=0 — it relies entirely on the STREAM to iterate. It provides
  no iteration itself. **WEDGES** (known: OP_EN-stuck-1, PC_TASK_STATUS stuck).

## A3 — the diff, the contradiction, and go/no-go

**The exact structural element mesa RK3576 whole-graph fails to emit:** the vendor's
kept **broadcast OP_EN (0x81/0x08 = 0x1d)** as the per-task re-fire, plus (for
different-address tasks) the **PC 0x10/0x14 next-pointer** and the **SYNC (0x41)**.
Mesa uniquely (a) substitutes the broadcast with per-unit OP_EN and (b) omits the
next-pointer by default. The proven-correct RK3588 path keeps the broadcast AND
patches the next-pointer — i.e. RK3576 and RK3588 use the SAME trailer grammar; only
mesa's RK3576 whole-graph packer diverges from it.

**Are RK3576 (task_number) and RK3588 (next-pointer) two different mechanisms?** No —
the vendor RK3576 stream carries BOTH: task_number = N (the stop count) AND the
in-stream next-pointer/broadcast trailer (the per-task advance+re-fire). RK3588 uses
the identical trailer. The "task_number iteration" and "next-pointer" framings are
the same one grammar seen from the kernel vs the stream.

**The contradiction that gates this (must flag):** mesa's reason for replacing the
broadcast is "PC reg 0x08 broadcast RESTARTS the PC and stalls." But the vendor
tiled-conv (`conv0_rk3576.rknn`) runs 4 tiles with that SAME broadcast (0x08 = 0x1d),
no next-pointer, and computes correctly. So the broadcast does NOT inherently
restart-stall the vendor PC. Either (i) the SYNC (0x41) barrier the vendor emits
before the broadcast is what makes it advance-not-restart, (ii) the next-pointer
being written just before the broadcast makes it commit-and-advance (broadcast alone
re-fires the SAME task because 0x10 still points at it -> looks like a restart), or
(iii) librknnrt rewrites the trailer at runtime and the compile-time .rknn is not
what the PC actually runs. Mesa's "restart" was observed WITHOUT the surrounding
vendor trailer (no SYNC, no next-pointer), so it is confounded.

### GO — worth implementing, with ONE cheap capture first
GO because there is a concrete, proven-on-the-sibling structural grammar (next-pointer
trailer + kept broadcast OP_EN + SYNC) that mesa RK3576 whole-graph does not emit,
and which plausibly drives the per-task advance+re-arm. The wedge is NOT "the stream
already carries the grammar and the PC wedges anyway" — mesa's stream is missing the
grammar (it replaced the re-fire and dropped the next-pointer/SYNC).

**Required next capture (do this before/with Phase B — the .rknn is compile-time):**
extend `vendor-capture/rknpu-regcmd-dump.patch` to dump the WHOLE task_number=N submit
buffer of a real multi-task run — from `first_task->regcmd_addr` for
`task_number * stride` u64 (all tasks + their trailers), not just the first task's
`regcfg_amount` entries. This gives the AUTHORITATIVE runtime trailer (absolute
next-pointer values, whether the broadcast/SYNC survive librknnrt), resolving the
compile-vs-runtime + broadcast-restart contradiction. (dirty/vendor.txt's task_number=2
capture has the SUBMIT header but not the per-task regcmd bytes — this is the gap.)

### Phase B scope (mesa `rkt_pack_graph_regcmd`, RK3576 whole-graph)
Reproduce the vendor trailer VERBATIM per packed task, ranked cheapest-first:
1. **KEEP the broadcast OP_EN 0x1d** — remove/bypass the L169-221 per-unit substitution
   for this mode (the single biggest divergence; the vendor tiled path shows broadcast
   + stride alone can iterate). ~5 lines.
2. **Emit the SYNC (0x41)** entry before the broadcast (mesa never emits it) — candidate
   for what makes the broadcast advance-not-restart.
3. **Patch the next-pointer** PC 0x10 = next task's absolute packed addr
   (graph_addr + (g+1)*stride_bytes), PC 0x14 = next amount, for every task but the
   last (last = 0 to terminate) — required once tasks are different layers/addresses
   (the multi-layer case). This is the existing ROCKET_NEXTPTR math; make it default
   for whole-graph AND ensure the fill emits the 0x10/0x14 slots unconditionally.
Order in the trailer must match the vendor: [0x10][0x14][SYNC][broadcast OP_EN] — the
next-pointer is written BEFORE the re-fire so the broadcast commits into the next task.
Kernel: keep task_number = N (the stop count); no kernel change expected.

**NO-GO trigger (if the capture refutes):** if the runtime full-buffer capture shows
the vendor does NOT carry this trailer at runtime (librknnrt strips it and the advance
is a mechanism no register/stream carries), then #1 is closed and the wedge is internal
PC behavior -> RTL. The compile-time .rknn says GO; the runtime capture confirms it.
