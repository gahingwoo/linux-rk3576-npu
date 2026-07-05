# Does RKNPU matmul/GEMM use the same CBUF→CSC→CMAC conv pipeline (and the chained-task wall)? (2026-07-05)

Gate-1 question: on the open mesa/rocket stack, conv MobileNet is blocked by ONE wall — in a submit that
chains multiple tasks, the non-cold-start task's CSC never re-arms (operands reach CBUF, but the CSC
weight-loader never drains it → empty CMAC → requant zero-point). Only the cold-start (first) task after
NPU-init MACs. A local LLM is matmul-heavy, not conv-heavy. Does RKNPU matmul run through the SAME pipeline
and the SAME multi-task-chain dispatch (→ same wall), or a different path / a naturally per-submit dispatch
(→ bypass)? Read-only analysis of the vendor rknpu driver, the RK3576 NPU register map (mesa registers.xml),
the rocket/mesa stack, and the NVDLA architecture.

---

## VERDICT

**SAME COMPUTE PIPELINE — but a real DISPATCH bypass exists.**

- **Pipeline (settled):** a matmul/GEMM on the RK3576 NPU is a **Fully-Connected (FC) mode of the ONE
  convolution core** (CNA→CBUF→CSC→CORE/CMAC→DPU). There is no separate matmul/GEMM unit. So a matmul that
  is CHAINED into a `task_number=N` submit hits the EXACT same CSC consume-arm wall as a chained conv.
- **Dispatch (the escape hatch):** the kernel is op-agnostic — conv and matmul use the identical
  `rknpu_submit`/regcmd/`task_number` path, so dispatch granularity is a userspace/regcmd choice that the
  OPEN stack fully controls. The wall is CHAINED-only: the first (cold-start) task always MACs. If each
  matmul is dispatched as its OWN independent submit (a fresh cold-start), it should compute — and the
  earlier SPREAD experiment (3 SEPARATE jobs → a non-degenerate output) is direct, if weak-oracle, evidence
  that a separate submit re-arms the cold-start.

**So: a local LLM on the open stack would BYPASS the wall IF its matmuls are dispatched per-op (cold-start
each) — the natural granularity for a matmul API / decode loop — and would HIT the same wall only if the ops
were chained into one `task_number=N` submit.** The wall is therefore NOT inherently fatal to an open-stack
LLM; it is fatal only to the whole-graph-chained dispatch mode.

The one thing standing between "suggested bypass" and "proven bypass": SPREAD used the weak `distinct` oracle
on the final BO only. The single most valuable confirming experiment is to re-run N separate single-task
submits with the clean per-task `dt_wr` + `zero_out_bos` oracle and confirm EACH separate submit's task MACs.

---

## Q1 — how is a matmul dispatched vs a conv in the vendor rknpu driver?

**Identically. The kernel is op-agnostic.** Enumerated all of `rk3576-vendor-kernel/drivers/rknpu/` — there
is not a single `matmul`/`gemm`/`fc` reference anywhere in the driver. The submit path (`rknpu_submit` →
`rknpu_job_commit_pc`) takes an opaque **regcmd** (a list of NPU register writes) plus `task_number`,
`core_mask`, `int_mask`, `task_base_addr`, and kicks the PC sequencer. It never inspects or interprets the op
type. Conv, depthwise, matmul, pooling, activation — all are just regcmd bytes generated in USERSPACE (the
RKNN model compiler / the matmul runtime).

Consequence: **the multi-task-chain dispatch (`task_number=N`) is the SAME mechanism for matmul and conv.**
Whether a matmul is chained or per-submit is decided entirely by whoever lays out the regcmd — not the
kernel. On the open stack, that layer is mesa/rocket, i.e. WE choose.

## Q2 — does matmul go through the CSC and the CBUF→CSC→CMAC operand path the wall sits in?

**Yes.** From the RK3576 NPU register map (`mesa .../rocket/registers.xml`), the compute-unit domains are:
`PC` (sequencer), **`CNA`** (Convolution front-end: CDMA + CSC + CBUF staging), **`CORE`** (CMAC/CACC MAC
array), `DPU`/`DPU_RDMA` (SDP: requant/activation/BN/BS), `PPU`/`PPU_RDMA` (pooling), `DDMA`/`SDMA`, `GLOBAL`.
**There is exactly ONE MAC datapath: CNA→CORE. No matmul/GEMM domain exists.**

Fully-Connected is a MODE of the CNA, sharing the CSC and CBUF:
- `CNA_CONV_CON1.CONV_MODE` (bitfield) — selects the conv mode (direct / Winograd / **FC**).
- **`CNA` domain contains `FC_CON0` (0x1060), `FC_CON1` (0x1064), `FC_CON2` (0x1074), `FC_DATA_SIZE0/1`
  (0x1084/0x1088), `FC_DATA_BANK` (bits 8-10), `FC_SKIP_EN`, `FC_SKIP_DATA`** — the FC config registers live
  INSIDE the convolution front-end, right beside `CONV_MODE`, the `CSC_DO_EN`/`CSC_WO_EN` (CSC data-out /
  weight-out enables) and `DATA_BANK`/`FC_DATA_BANK` (CBUF bank selects).
- `FC_DATA_BANK` selecting a CBUF bank is proof FC operands stage through the SAME CBUF the wall sits in, and
  are drained by the SAME CSC (`CSC_WO_EN`) weight-loader that never re-arms on a chained conv.

Corroboration from the open stack itself: `rkt_regcmd.c` ALREADY emits `FC_CON0/1/2` as part of its regular
conv regcmd (lines 881-888), and its own notes record that **`FC_CON1=0x777` is load-bearing — with
`FC_CON1=0` the CMAC never produces a MAC result** (rkt_regcmd.c:136-140). So the FC registers are not a
separate feature; they are part of the one CNA→CMAC datapath even for a plain conv. A matmul just sets
`CONV_MODE=FC` and the FC_* geometry; it feeds the identical CSC/CBUF/CMAC.

**⇒ A chained matmul stages into CBUF and depends on the exact CSC consume-arm that fails for a chained conv.
Same stage, same wall.**

## Q3 — dispatch granularity: one task per submit, or chained multi-task?

Two layers to separate:

**(a) What is POSSIBLE (kernel):** because the kernel is op-agnostic (Q1), a matmul can be dispatched EITHER
as one task per submit (independent, cold-start each) OR chained into a `task_number=N` whole-graph submit.
The choice is the userspace regcmd layout's, and the open stack owns it.

**(b) What is NATURAL for a matmul / an LLM:** the whole-graph `task_number=N` chaining is what the RKNN
model-graph compiler does for a fixed CONV GRAPH (e.g. MobileNet's 28 layers) to amortize per-layer dispatch
overhead into ONE submit. A raw matmul — the RKNPU `rknn_matmul_*` API, on which RKLLM builds — is naturally
a per-CALL submit (one matmul op = one job), because matmul shapes/operands are supplied at call time in a
decode loop, not baked into a static graph. **So the natural granularity for LLM matmuls is per-op
independent submits, which is precisely the cold-start-each case that bypasses the chained wall.** (This is a
HYPOTHESIS about the vendor matmul runtime's dispatch — no matmul `.rknn` and no `rknn_matmul_api.h` are
present in the trees to inspect directly. But it does not gate the answer: on the open stack we CHOOSE per-op
regardless of what the vendor does.)

**Direct positive evidence that separate submits re-arm the cold-start** (`dirty/npu-test/rr_spread.log`):
the SPREAD replay ran a 3-task chain as **3 SEPARATE jobs × 1 task each** (`mode=SPREAD (N jobs x 1 task)`,
`submit: 3 job(s)`), and the final output was `distinct=254 nonzero=202547/204800 -> COMPUTED
(non-degenerate)` — i.e. running the layers as separate submits produced a real result, unlike the
whole-graph-chained mode where every non-cold-start task is empty. CAVEAT: this used the weak `distinct`
oracle on the FINAL BO only (per [[feedback-metric-discipline]], `distinct` can reflect stale data; the clean
oracle is per-task `dt_wr` with `zero_out_bos`). And the later `conv0_twice` "pure position" result (2nd task
does NOT MAC) was measured for a RE-KICK within ONE job, NOT a separate submit — the driver re-runs
`pp_state_init` + a fresh PC kick per JOB, so a separate submit is a fuller cold-start than a re-kick. The
per-submit re-arm is therefore SUGGESTED and mechanistically plausible, but not yet confirmed with the clean
per-task oracle. That confirmation is the pivotal next experiment for any open-stack LLM.

## Q4 — NVDLA cross-check: is GEMM a distinct op, or 1×1 conv through the same CSC?

NVDLA (which the RKNPU RK356x/RK3588/RK3576 generation derives from) has a **single convolution core**
(CDMA → CBUF → CSC → CMAC → CACC). Fully-connected / GEMM layers are executed BY that convolution pipeline as
a special case — there is no separate matmul engine in NVDLA. The RK3576 register map inherits this exactly:
the FC config is a `CONV_MODE` + `FC_CON*` registers INSIDE the `CNA` convolution domain (Q2), not a distinct
block. So on this architecture **GEMM == conv through the same CSC path** → it hits the SAME consume-arm wall
when chained. (Register/field semantics — `FC_*` = fully-connected feeding CSC/CBUF, `CONV_MODE` selects it —
are read from the register names + the NVDLA convolution-core architecture; the RK3576 compute regs are
undocumented, so treat the exact FC micro-behavior as a well-supported hypothesis, not a datasheet fact.)

## Q5 — does mesa/rocket have any matmul primitive today; net-new scope?

**No matmul/FC dispatch exists today.** The Teflon/Gallium `pipe_ml` path in `rkt_ml.c` implements only two op
types: `PIPE_ML_OPERATION_TYPE_CONVOLUTION` (regular + depthwise) and `PIPE_ML_OPERATION_TYPE_ADD`. There is
no `MATMUL`/`FULLY_CONNECTED` op type in the current mainline Gallium ML interface at all.

Net-new effort to add a matmul path, split by reuse:
- **REUSED as-is (the whole dispatch spine):** the kernel submit/engage/PC path (op-agnostic), `rkt_task.c`
  submit, the regcmd packer/emit framework, CBUF config, and the DPU requant/output-convert stage. rocket
  ALREADY emits the `FC_CON0/1/2` registers in its conv regcmd, so the register plumbing is present.
- **NET-NEW (moderate):**
  1. A `pipe_ml` MATMUL/FULLY_CONNECTED op type in Gallium + the Teflon frontend lowering that routes a
     TFLite `FULLY_CONNECTED` / matmul tensor op to it (upstream Mesa ML-interface change, not just rocket).
  2. The FC-mode regcmd config in `rkt_regcmd.c`: set `CONV_MODE=FC`, program `FC_CON0/1/2`, `FC_DATA_SIZE`,
     `FC_DATA_BANK`, `FC_SKIP` for the matmul geometry (M/N/K instead of conv H/W/C). This is an EXTENSION of
     the existing conv regcmd builder, not a new datapath.
  3. int8/fp16 matmul requant/scale in the DPU stage — the conv requant (already solved for int8 conv, see
     [[project-rk3576-requant-bs-scale]]) is directly adaptable; RK3588's int8 matmul is already solved
     end-to-end ([[project-rk3588-int8-is-solved]]) and is the reference.
  4. **Per-op dispatch choice:** to get the bypass, emit each matmul as its OWN submit (one task per job)
     rather than packing into the whole-graph chain — a dispatch-policy change in the rocket subgraph
     builder, low code cost.

Rough size: a focused FC/matmul bring-up (one op type, per-op dispatch, int8 first) is a MODERATE addition —
most of the hard parts (submit, engage, CBUF, requant, and even the FC registers) already exist; the genuinely
new work is the Gallium op type + Teflon lowering and the FC geometry programming.

---

## Bottom line for gate 1

- A local LLM's matmuls run through the **same** CNA→CBUF→CSC→CMAC pipeline as conv (FC is a `CONV_MODE`,
  no separate unit) → a matmul CHAINED into a `task_number=N` submit hits the **same** CSC consume-arm wall.
- BUT the wall is chained-only, and dispatch granularity is the open stack's to choose. Dispatched **per-op
  (independent cold-start submits)** — the natural granularity for a matmul API / LLM decode loop — a matmul
  should compute, and the SPREAD separate-jobs result is positive (if weak-oracle) evidence it does.
- **So an open-stack local LLM can BYPASS the wall by dispatching matmuls per-op instead of whole-graph
  chained.** This does NOT require solving the RTL-level cold-start consume-arm.
- **Pivotal confirmation before investing:** re-run N separate single-task submits with the clean per-task
  `dt_wr` + `zero_out_bos` oracle to prove each separate submit re-arms the cold-start (SPREAD only showed a
  non-degenerate final BO under the weak `distinct` oracle). If confirmed, the matmul path is a MODERATE
  net-new build (Gallium FC op type + Teflon lowering + FC-mode regcmd; dispatch/submit/engage/CBUF/requant
  all reused), with RK3588's solved int8 matmul as the reference.

Trade-off to note: per-op dispatch pays a full submit+engage per matmul. For an LLM with many matmuls per
token that is a throughput cost, but it is a WORKS-first route that sidesteps the RTL wall — the right first
target for an open-stack LLM on RK3576.
