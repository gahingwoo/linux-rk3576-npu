# RK3576 NPU chained CMAC: why the open-source black-box route stops here

**Status: parked (2026-07-10), pending new evidence.** Every software-observable
dimension has been tested to a clean, reproducible negative. Reopening this needs
either vendor RTL/TRM access or a new runtime signal nobody has found yet — not
another pass over dispatch, registers, cache, or config. See "What would reopen
this" at the end.

## The bug, stated precisely

On the RK3576 NPU, a job containing more than one task — the normal case for any
multi-layer network, and the only case that matters for real inference or an
LLM's chain of matmuls — computes correctly for exactly one task: the first task
run after the NPU's power domain comes on. Every task after that, in the same
powered session, engages the compute units, DMAs its input, and advances the PC
sequencer's own bookkeeping — but its CMAC accumulator never actually produces
output. The buffer it should have written stays at whatever it held before (a
requantization zero-point, or an untouched fill pattern if you pre-poison it).

This holds under the vendor's closed `rknpu` driver's exact dispatch grammar,
reproduced bit-for-bit on the open `rocket` driver. It holds whether the tasks
are dispatched as N sequential single-task kicks, as one hardware-native
`task_number=N` iteration, or as N fully independent job submissions with no
chaining relationship at all. The one thing that reliably "fixes" it is a full
NPU power-cycle between tasks — which is not a fix, it is the absence of the bug
under a condition (a power-cycle per compute op) no real workload can afford.

Two independent investigations converged on this same terminus by different
routes: an exhaustive rocket-only sweep (`FINDINGS.md`, 2026-07-02–07-05) and a
same-kernel vendor-vs-rocket cross-check (`FINDINGS-DUAL-IMAGE.md`, this repo,
2026-07-08–07-10) that reproduces both drivers on one mainline-7.1.3 image
specifically so "the vendor does X, rocket doesn't" claims are measured, not
inferred across two different kernels. A third pass — an independent, source-
only re-audit that deliberately didn't read either of the above first — found no
surviving candidate either; its two leads each turned out to duplicate work
already done and closed (below).

## Method: falsification, not confirmation

The rule followed throughout was: a "ruled out" claim needs a clean run that
would have shown the opposite if it were true, not an inference from a comment
or a config that "should" work. Several early conclusions in this project's own
history were later overturned by exactly this standard — see the ledger's own
entries reversing earlier verdicts (Phase B trailer fix reversed a premature
"internal wall" call; the stale-TLB fix turned out to be a silent no-op on
mainline `rockchip-iommu` that had never actually run). The standard applied
here: for each candidate below, is there a specific experiment whose result
would have looked *different* if the candidate were the real cause? If yes, it
was run; if the result matched "candidate present, bug still there" or
"candidate absent, bug still there" either way, the candidate is refuted, not
merely unconfirmed.

## Falsification ledger

| Dimension | Candidate | Test | Result |
|---|---|---|---|
| **Dispatch mechanism** | Sequential per-task kicks are wrong; hardware-native iteration is needed | Rebuilt the exact vendor grammar: single `PC_OP_EN` pulse, `TASK_CON.task_number = N`, contiguous 64-byte-strided task regcmds with the vendor's self-iterating trailer (`[next-addr][next-amount][SYNC][broadcast OP_EN]`), reverse-engineered from a runtime wtrace of the vendor's own `task_number=8` submit and confirmed byte-identical to its compile-time form | **Refuted.** `PC_TASK_STATUS` genuinely advances (1→6), all four compute units engage (`exec_ever=0xf`), DMA is clean, `PC_DONE` fires clean. The PC mechanism works exactly as designed. Every task after the first still computes empty. |
| | Native hardware iteration with zero driver intervention mid-run (`bare_tasknum`) | Strip every driver register touch during the run so the PC walks the chain with no software in the loop at all | **Refuted.** Byte-identical result to the driven case. |
| | The escape hatch: skip chaining entirely, dispatch every task as its own fully independent job | N independent single-task submits, each its own driver-level job, one reading the previous op's real (correct) output as input | **Refuted, decisively.** Only the very first submit after each power-domain resume computes; every subsequent *independent* submit is empty, even one reading verified-correct upstream data. This rules out chaining, trailers, PC state, and task_number as the cause outright — there is no chain in this test. |
| | Vendor uses a descriptor-array DMA-fetch mechanism (`TASK_DMA_BASE_ADDR` → array of task descriptors) rocket never replicated | Live wtrace of the vendor's own submit register writes | **Refuted.** `task_base_addr = 0` in the vendor's own capture, at `task_number=2` and `task_number=8` alike. The vendor doesn't use this mechanism either. |
| **Register / config** | Some CNA/CORE/DPU/RDMA config register differs for chained vs. single-task | Forced the *entire* regcmd config (88 CNA + 8 CORE + 67 DPU + 20 RDMA registers) from the known-good single-task capture into a chained task's context | **Refuted.** No effect; the first task even degraded under the forced write, proving the writes reach the hardware — the config is not what's missing. |
| | Ping-pong buffer selection / ping-pong config latch | Swept the producer/consumer ping-pong pointer directly | **Refuted.** True negative (confirmed non-inert: it did move the write path, output flipped from untouched to zero-point-written — the config write lands — but the MAC accumulator stays empty either way). |
| | Driver's own submit-register *values* differ from the vendor's, task-for-task | Instrumented writel on both drivers on one identical kernel, value-for-value diff across a full inference | **Refuted.** Match, apart from two explainable differences (rocket clears more interrupt bits than the vendor, strictly a superset; task count differs because the two captured workloads differ in layer count) |
| **On-chip data staging (CBUF)** | Feature/weight data never reaches the on-chip CBUF for chained tasks | PRE/POST CBUF SRAM audit around a chained task's execution | **Refuted.** The chained task's real data (input from the prior layer) demonstrably lands in CBUF (windows change PRE→POST, correct byte content) — the CMAC still doesn't consume it. |
| | Chained task reads stale/zeroed intermediate data, not the real prior-layer output | Direct probe of a chained task's input BO immediately before its kick | **Refuted.** It reads the real, correct upstream output. Computes zero anyway. |
| **Cache / DMA coherency** | The "empty output" is a stale CPU-cache read, not a real empty write | Explicit `dcache_inval_poc` forced invalidate + re-read on a buffer pre-filled with a sentinel, immediately before job dispatch, plus separate confirmation the fence/wait path can't release before write-back | Both **refuted** as artifacts: forced-invalidated read matches the "stale" read exactly — the buffer is genuinely never written. |
| **IOMMU / TLB** | A stale IOTLB entry serves a previous BO's translation for a reused IOVA | Discovered mainline `rockchip-iommu` implements neither `flush_iotlb_all` nor `iotlb_sync` — so the project's own earlier "fix" (calling `iommu_flush_iotlb_all()`) was a **silent no-op** the whole time. Implemented a real per-submit TLB ZAP-cache handler, confirmed firing on wtrace | **Refuted** (with a real, independent bug found and fixed along the way — see below). Wall persists with a genuine, verified-firing TLB flush in place. |
| **Direct register writes, whole-address-space** | Some writel the vendor makes that rocket doesn't, anywhere in the NPU block or IOMMU, across a complete inference | Full ftrace-based writel/readl instrumentation on both drivers, same kernel, set-diffed | **Refuted.** Identical write sets. |
| **Environment (clock/power/genpd/QoS)** | Some clock, power-domain, or regmap operation the vendor performs that rocket skips | ftrace on `regmap_reg_write` + clk + genpd + iommu tracepoints, cold boot, both drivers, same kernel, set-diffed | **Refuted.** Identical apart from unrelated non-NPU housekeeping. |
| **Clock rate / PVTPLL** | NPU compute clock needs vendor-specific PVTPLL tuning via SCMI | Traced and forced the SCMI `clk_set_rate` path | **Refuted** — dead end, made zero jobs compute either way. |
| **Firmware / TF-A / OP-TEE** | Vendor uses different secure firmware that enables something mainline can't reach | Confirmed the board boots the *same* vendor SPI firmware (Rockchip TF-A + OP-TEE) under both the vendor-driver and rocket-driver boot paths | **Refuted.** Same firmware either way. |
| **Completion / IRQ path** | Fence signals before hardware genuinely finishes, masking a real (slow) write as absent | Traced: RK3576 can't route `PC_DONE` to the GIC at all — completion is polled from `INTERRUPT_RAW_STATUS`, with a bounded forced-timeout fallback. Compared against the vendor's own completion path, which also polls task-status directly rather than depending on a hard IRQ | Consistent with the wall in principle but not what causes it — the same "empty" result reproduces even when completion is confirmed via a real, non-timeout status read (`PC_DONE` genuinely fires; the accumulator is still empty at that point). |

## What survives, and what it means

Nothing does. Dispatch mechanism, register values, config geometry, CBUF data
staging, cache coherency, IOMMU/TLB state, the complete NPU-block and IOMMU
write set, clock/power/genpd environment, and firmware are each independently
falsified as the cause, across two structurally different investigations plus a
third blind pass that found nothing new.

What's left is a positive characterization, not a process of elimination by
default: the CMAC's compute-arm is a resource scoped to the **NPU power
domain's on-state**, not to any per-task or per-submit software action. The
compute pipeline visibly runs — units engage, DMA moves real data, the PC state
machine advances exactly as programmed — for every task, but the actual
accumulate-and-commit step fires exactly once per power-on, independent of
dispatch mechanism, chaining, or register content. That is consistent with an
internal sequencer/microcode latch, or an undocumented one-shot enable state,
that isn't exposed through any register this project can find — which is
exactly the kind of thing that needs the vendor's TRM or RTL to actually see,
not another register trace.

## What this search did produce

Two things worth keeping independent of the negative result:

- **A real, upstreamable bug in mainline `rockchip-iommu`**: it implements
  neither `.flush_iotlb_all` nor `.iotlb_sync` in `default_domain_ops`, so any
  driver calling the generic `iommu_flush_iotlb_all()` API gets a silent no-op
  — the callback is simply absent, and the IOMMU core skips a NULL callback
  without complaint. This project's own earlier TLB-flush "fix" had been
  running that no-op the entire time. A real fix (`kernel/0025`) is
  implemented and confirmed firing.
- **The vendor's RK3576 multi-task dispatch grammar, reverse-engineered from a
  runtime capture and confirmed against the compile-time `.rknn`**: each task
  ends in a self-iterating trailer — an absolute pointer to the next task's
  regcmd, its fetch amount, a `SYNC`, and a broadcast `OP_EN` that re-fires the
  PC into the newly-pointed task rather than restarting it. This resolved a
  standing confusion in Mesa's own RK3576 whole-graph packer (which had
  substituted a different, non-working engage sequence on the mistaken belief
  that the broadcast always restarts the PC) and is upstream-relevant to
  `mesa/src/gallium/drivers/rocket` regardless of the deeper wall.

Neither of these closes the bug. Both are real, verified, and useful to anyone
else working on this driver.

## What would reopen this

- Vendor TRM access describing the CMAC/CBUF consume-arm sequencing, or any
  documentation of a one-shot enable/latch tied to power-domain state.
- Silicon-level debug (JTAG, an internal register map beyond what's memory-
  mapped and documented for `rocket`/`rknpu`) capable of observing the actual
  microsequencer state across a chained task boundary.
- A genuinely new runtime signal — not a re-run of any test above under a
  different name. If you have one, the falsification ledger above is the bar
  it needs to clear.

## Would fp16 reopen this? — leans no (checked 2026-07-10)

A natural hope: the whole wall was hit under int8 (MobileNet UINT8); fp16 was
never run chained on rocket. Maybe fp16 sidesteps it. Two propositions were kept
separate, and one was answered without a port:

- **fp16 precision path works, and bypasses the int8 blob** — verified. A real
  vendor w4a16 matmul's regcmd, captured off this silicon, confirms the 16-bit
  recipe: `CNA_CONV_CON1.PROC_PRECISION = 2`, `DPU_DATA_FORMAT = 0xa0000002`, and
  `DPU_OUT_CVT = identity` (offset 0, scale 1 — no requant). The identity OUT_CVT
  is the point: the 16-bit path never reads the value-dependent int8 coefficient
  surface that `FINDINGS-FLOATSURFACE.md` proved underivable. So fp16 is the
  upstreamable path for single-op inference, independent of the wall.
- **fp16 breaks the chained wall** — *not* verified, and the existing record
  leans against it. The wall is localized (`CSC-CONSUME-REVIEW.md`) to the CSC
  consume/weight-load *trigger* — a per-task re-arm of an internal consumer
  credit/latch, armed once at cold-start. That trigger is *downstream* of CBUF
  staging (data and weights demonstrably reach CBUF; "not a weight-DMA failure")
  and *independent of weight content* (conv0_twice: the same int8 conv computes
  as task 0, goes empty as a follow-on kick). The wall is position / power-session
  dependent, not weight dependent. fp16 changes the weight *format/staging*
  (hardware DCOMP of 4-bit weights → software-flat fp16), which is upstream of and
  orthogonal to the failing trigger; precision is a property of the op, not its
  position. The one software re-arm lever (per-task PP_CLEAR / CSC re-arm, mesa
  `ROCKET_CSC_REARM`) was already tested and failed.

Not a proof (the trigger is undocumented internal state), but the burden now sits
on "fp16 breaks the wall," with nothing supporting it. Conclusion: don't build a
multi-day w16a16 port *to break the wall* — the evidence says it won't. Build fp16
only for its own value (blob-free single-op inference), and treat the chained-fp16
run as a cheap rider with an expected-negative result.

## Repro

The same-kernel cross-check (vendor `rknpu` and open `rocket` booting off one
mainline-7.1.3 image via two DTB variants) is in `/home/parallels/Documents/kiln`
(`FINDINGS-DUAL-IMAGE.md`, `capture/env-trace.sh`, `capture/wtrace-diff.py`).
The rocket-only sweep's full chronological log, including every reversed
verdict and dead end along the way, is `FINDINGS.md` in this repo. The vendor
dispatch grammar reverse-engineering is `WHOLEGRAPH-GRAMMAR.md`. Kernel patches
`0025`–`0028` in `kernel/` carry the TLB fix, the cross-stack instrumentation,
the cache probe, and the settled dispatch consolidation, in that order.
