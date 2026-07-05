# CBUF→CSC→CMAC consume — was the CSC drain/weight-load trigger ever touched? (2026-07-05)

Read-only review. The dispatch/iteration half is closed (trailer 29/29, weights present, all units engage,
DMA clean) yet chained CMAC outputs zero-point. Question: was the CSC consume/weight-load trigger (the stage
that makes the CMAC drain CBUF) ever touched by prior work, or is it the one untouched lever behind
"cold-start-only MAC"? Register semantics for the RK3576 compute block are undocumented in the TRM — every
mapping below is flagged as a HYPOTHESIS.

## Pipeline (NVDLA-derived, general architecture — not RK3576-verified)
DRAM --CDMA--> CBUF (ping-pong banks) --CSC--> CMAC --> CACC --> DPU/SDP --> DRAM.
- **CDMA** (= RK3576 CNA block, target 0x0201, regs 0x1000): loads feature+weight from DRAM into CBUF banks.
- **CSC** (Convolution Sequence Controller): reads CBUF and feeds the CMAC. Two loaders — **CSC_DL** (data)
  and **CSC_WL** (weight loader, pulls weights from CBUF into the CMAC weight registers). The CSC starts
  consuming when the CDMA signals a CBUF bank is ready (an internal **producer/consumer credit** handshake),
  and advances the ping-pong consumer pointer per task.
- **CMAC** (= RK3576 CORE block, target 0x0801, regs 0x3000): the multiply-accumulate array.
- On RK3576 there is NO separate CSC regcmd target (targets are CNA/CORE/DPU/RDMA only) — so the CSC is
  folded into the CNA and/or CORE blocks; its "start consuming" trigger is either a field in those blocks or
  an internal CDMA↔CMAC handshake with no CPU-visible register.

## PART 2.1 — classify every prior CBUF-related experiment: CBUF-SIDE vs CSC-SIDE

| experiment | what it touched | class | result |
|---|---|---|---|
| cbuf_reset (per-job CBUF/AXI reset variants) | CBUF bank state / reset | **CBUF-SIDE** | DEAD (breaks compute) |
| NBUF / cache_sgt SRAM operand cache (0x3fe80000) | operand STAGING location | **CBUF-SIDE** | RULED OUT (graph runs from DRAM; conv0 computes without it) |
| CBUF audit_all (16×64KB PRE/POST diff) | DIAGNOSTIC | observation | proved DATA REACHES CBUF (dw1 out changed 6 windows, nz→dense) yet CMAC=0 |
| CBUF_CON0/CON1 bank config (DBANK/WBANK/DENTRIES) | CBUF bank ALLOCATION | **CBUF-SIDE** | live=0x44 same both layers; DENTRIES per-layer; regcmd DBANK never latches |
| CBUF_CON0 bit26 clear on intermediate tasks | data-reuse (read input from CBUF vs DRAM) | CBUF-SIDE-ish | did NOT make them read prior output; no help |
| geom_both (config → both PP groups) | regcmd config, both ping-pong groups | **REGCMD-config** | REFUTED (dw1 still empty; degraded conv0) |
| geom_all (CPU-write EVERY regcmd register) | ALL regcmd config VALUES | **REGCMD-register** | CLOSED (no regcmd register is the miss; corrupts conv0) |
| warm-chain (skip per-kick pp_state_init) | dispatch (keep CBUF warm) | dispatch | got later layers to engage+DMA |
| rawor CSC bit probe | DIAGNOSTIC | observation | CSC=0 for conv0 (which COMPUTES) too → uninformative, "CSC never fired" retracted |
| pp_alt (alternate PRODUCER S_POINTER POINTER bit0) | ping-pong PRODUCER group | ping-pong | CLOSED (chained still empty; reached HW, moved write path, not MAC) |

**Finding: every prior experiment was CBUF-SIDE (staging / reset / bank / SRAM / data-reuse) or REGCMD-config
(the register VALUES). The CSC CONSUME/weight-load TRIGGER — the thing that makes the CMAC start draining
CBUF, and the CSC_WL that loads weights from CBUF into the CMAC — was never a direct target.** The closest
misses: geom_all forced all regcmd *values* (but the CSC consume is not obviously a regcmd config register);
pp_alt moved the *producer* pointer (not the consumer/CSC side); the CORE OP_EN (0x3008) is emitted per task
(so the CMAC/CSC IS re-triggered per task) but that clearly is not sufficient.

## PART 2.2 — where the earlier "weights don't reach the MAC" left off
Localized (single-task work, [[project-rk3576-conv0-weightlayout]] / dispatch step-2) to: **"the CMAC
operands (weights and/or input) do NOT reach the CMAC from CBUF, INDEPENDENT of weight content"** — i.e. a
CBUF→CSC→CMAC consume/load issue, NOT a weight-DMA failure and NOT a weight-value/layout bug (conv0's own
layout was separately fixed and conv0 now computes byte-real). The weight-load TRIGGER itself was never
isolated — only the weight regcmd *value* (now confirmed present + plausible per task: addr 0x1110, size
0x101c). So the open gap is exactly the CSC_WL "start loading weights from CBUF into the CMAC" step.
NB core wt_rd=0 is NORMAL (weights count in top wt_rd) — it is NOT evidence the CSC_WL didn't run; the
evidence is the zero-point output (empty accumulator) with data confirmed in CBUF.

## PART 2.3 — is the CSC trigger reachable by software? Ranked levers (distinct from the above)
Zero-point output = empty accumulator = the CMAC ran with no operands from CBUF. Data is in CBUF; the CORE
OP_EN fires per task; the trailer broadcast now fires per task. So what's missing is a per-task RE-ARM of the
CSC/ping-pong CONSUME state that the cold-start reset sets once and nothing re-applies during the HW walk.

1. **[regcmd trailer, DISTINCT, testable] per-task CSC/ping-pong re-arm via S_POINTER PP_CLEAR in the
   trailer.** The cold-start pp_state_init issues POINTER_PP_CLEAR (S_POINTER=0x1e) ONCE; the self-iterating
   whole-graph walk never re-arms it per task. The vendor's HW iteration re-arms the CSC/consumer per task
   internally. Inject a PP_CLEAR (CNA 0x1004 / CORE 0x3004 with the PP_CLEAR bits, or the 0x1004 toggle
   sequence) into EACH task's trailer, so the CSC weight-load/consumer state re-arms per task. DISTINCT from
   pp_alt (producer POINTER bit0, not the CLEAR) and from per-job pp_state_init (once). HYPOTHESIS: the exact
   "CSC re-arm" bit is unproven; POINTER/EXECUTER_PP_CLEAR (S_POINTER bits 4/5) is the best-mapped candidate.
   Reachable from mesa (trailer) or the driver. Cheapest first test.
2. **[weaker, regcmd] a separate WEIGHT-reuse control in CBUF_CON0.** The DATA-reuse bit (26) was tested
   (clearing it didn't help). If RK3576 has a SEPARATE weight-reuse/weight-load-enable bit (shifted from the
   RK3588 CBUF_CON0 WEIGHT_REUSE@13) that mesa sets wrong, chained CSC_WL may skip. LOWER prior: a stuck
   weight-reuse would reuse conv0's weights → wrong-but-nonzero output, not zero-point (empty). Needs the
   RK3576 CBUF_CON0 field map (partial in vendor-capture) to even locate the bit.
3. **[likely internal → RTL] the CDMA→CSC producer/consumer credit + weight-load-done latch.** If #1/#2
   fail, the consume arm is internal sequencer state (a credit/latch the cold-start reset initializes and no
   per-task register re-arms). Both the regcmd-register space (geom_all) and the driver-register space
   (writel audit found NO gap) are already exhausted, so if a per-task trailer re-arm (#1) also fails, there
   is no remaining software-writable path → the CSC consume arm is the cold-start internal context = RTL.

## Honest bottom line
The CSC consume/weight-load trigger is the **one untouched lever** — all prior work was CBUF-side staging or
regcmd VALUES, never a per-task CSC re-arm SEQUENCE. There IS a concrete, software-reachable, distinct thing
to try before any RTL verdict: **#1, inject a per-task PP_CLEAR / CSC re-arm into the trailer** (the walk
never re-arms the consumer the cold-start reset set once). Only if that fails is the internal-sequencer/RTL
conclusion justified — and at that point it would be, because geom_all (all regcmd regs) + the writel audit
(all driver regs) + a per-task re-arm sequence would together exhaust the software surface. Register-mapping
claims here are hypotheses (RK3576 compute regs are undocumented); #1 is the falsifiable next step.
