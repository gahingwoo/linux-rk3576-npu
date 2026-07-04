# RK3576 NPU writel audit — vendor rknpu vs open rocket (2026-07-04)

Goal: is there ANY NPU register write the vendor rknpu driver makes across a full
inference that the open rocket driver does not? Part 1 = complete static
enumeration + diff (below). Part 2 = a line-diffable live writel trace built into
both stacks (branch `rk3576-writel-trace`; `vendor-capture/diff_writel_trace.py`).

## Method
- Enumerated every NPU-register `writel` in the vendor rknpu driver
  (`rk3576-vendor-kernel/drivers/rknpu/`) for the RK3576 config, across ALL
  functions (not just commit_pc): probe/state_init, soft_reset, subcore_commit,
  commit_pc, irq_handler, job_next/job_done, clear_rw_amount, the action ioctl,
  bw_priority, power/clk.
- Enumerated every NPU-register write in rocket's default path
  (`job_run`→`hw_submit`→`handle_irq`→`core_reset`/`pp_state_init`), knobs off.
- Cross-checked against the captured vendor logs: `vendor-live-cap.txt`
  (single-task, `task_number=1`) AND `dirty/vendor.txt` (multi-task,
  `task_number=2`).

## Vendor's complete NPU-register write set (RK3576)
RK3576 config: `pc_task_number_bits=16`, `pc_dma_ctrl=1`, `num_irqs=2`,
`state_init=rk3576_state_init`, `cache_sgt_init=rk3576_cache_sgt_init`.

- **Probe + every soft_reset** — `rk3576_state_init`:
  `0x10=1`, `0x1004=0`, `0x1024=0x80000000`, `0x1004=1`, `0x1024=0x80000000`,
  `0x1004=0x1e`. (Primes BOTH ping-pong groups, then S_POINTER=0x1e.)
- **Per submit** — `subcore_commit` → `commit_pc`:
  1. `0x10 (PC_DATA_ADDR) = 0x1`   ("switch to slave mode")
  2. `0x1004 (CNA_S_POINTER) = 0xe`, `0x3004 (CORE_S_POINTER) = 0xe`  (num_irqs>1)
  3. `0x10 (PC_DATA_ADDR) = first_task->regcmd_addr`
  4. `0x14 (PC_DATA_AMOUNT) = (regcfg_amount+4+2-1)/2 - 1`
  5. `0x20 (INT_MASK) = last_task->int_mask` (=0x300)
  6. `0x24 (INT_CLEAR) = first_task->int_mask` (=0x300)
  7. `0x30 (PC_TASK_CON) = ((0x6|pp_en)<<16) | task_number`
  8. `0x34 (PC_DMA_BASE_ADDR) = args->task_base_addr`
  9. `0x8 (PC_OP_EN) = 1`, then `0x8 (PC_OP_EN) = 0`   (the pulse)
- **Per IRQ** — `irq_handler`: `0x24 (INT_CLEAR) = 0x1ffff`. Then `job_done`
  re-submits ONLY if `task_number > max_submit_number (65535)` — never for a
  MobileNet, so a full graph is ONE submit and the IRQ just clears+completes.
- **Perf** — `clear_rw_amount`: `0x2210/0x2410 = 0x80000101` then `0x101`.
- **No other NPU writes anywhere.** The action ioctl exposes no arbitrary
  register write; bw_priority is disabled on RK3576 (`bw_priority_addr=0`); there
  is NO register-BAR mmap to userspace; power/clk use the pm/clk/reset frameworks
  (no NPU writel); NBUF/SRAM is set up by IOMMU mapping, not a register write.

## Rocket's NPU-register write set (default path)
Per task (`hw_submit`): `0x10=1`; `0x1004=0xe`, `0x3004=0xe`; `0x10=regcmd`;
`0x14=amount` (same formula); `0x20=0x300`; `0x24=0x300|PC_DONE`; `0x30=(0x7<<16)|1`;
`0x34=0`; perf `0x2210/0x2410`; `0x8=1`, `0x8=0`. Plus `pp_state_init` per job
(same 6 writes as vendor state_init) and INT_CLEAR at completion.

## DIFF — ranked
There is **no register offset the vendor writes and rocket never does.** Every
vendor per-submit write has a rocket equivalent with the same value. The only
multiset differences are rocket writing MORE, not less (per-job `pp_state_init`,
`0x24` also clearing PC_DONE bits) — not a gap.

The two decisive facts:
- **`0x34 (PC_DMA_BASE_ADDR)=0` even for `task_number=2`** (dirty/vendor.txt).
  This kills the "descriptor-DMA dispatch" idea outright: the vendor iterates 2
  tasks from one submit with the task-descriptor base = 0. rocket writes 0 too.
- **The per-submit register sequence is identical** (already known byte-for-byte;
  reconfirmed here against both the 1-task and 2-task captures).

So the vendor's ONLY advantage is **structural**, not a missing writel: it issues
ONE submit with `task_number=N` and lets the **PC hardware iterate all N tasks**
from a single OP_EN pulse (ping-pong group advancing in HW; the next task's
regcmd found from the regcmd stream, since `task_base_addr=0`). rocket either
wedges in that mode (`wg_continuous`) or routes around it with N single-task
kicks (`seq-kick`), where only the cold-start task MACs.

### Candidates to test (ranked by likelihood × cheapness)
1. **[structural / mesa, NOT a kernel writel] regcmd not laid out for PC
   auto-advance.** (a) The vendor's whole graph runs as one `task_number=N`
   submit; the PC advances task→task using the regcmd stream + the amount stride
   (`+4 EXTRA` = per-task stride), with `task_base_addr=0`. (b) rocket's
   `wg_continuous` writes the same registers but the PC does not iterate → wedge;
   mesa emits the RK3588 next-pointer/contiguous layout only for `soc!=RK3576`.
   (c) Hypothesis: RK3576 needs the per-task regcmd stream contiguous/chained so
   the PC's own iterator finds task 1; rocket/mesa never build it. (d) NOT a
   small kernel change — needs the mesa RK3576 regcmd layout. This is the real
   whole-graph mechanism; the live trace confirms it (vendor = 1 submit for N
   tasks, no extra per-task CPU writel).
2. **[kernel-visible, cheap, possibly untested cleanly] ping-pong POINTER never
   advances per seq-kick task.** (a) The vendor sets S_POINTER=0xe once and the
   PC advances group 0→1→0… per task in HW. (b) rocket hardcodes `pp_pointer=0`
   every kick (`hw_submit`: `pp_task_idx++` is computed but unused) → every
   seq-kick task runs on group 0. (c) Hypothesis: the second task's executer must
   read the fresh alternate group; forcing POINTER = `pp_task_idx & 1` per kick
   may arm it. (d) Small driver change. Caveat: `geom_both` (config forced into
   both groups) did not compute dw1 — weak counter-indication, but it forced
   config, not the executer's ACTIVE-group selection per task, so not identical.
3. **[known knob, unlikely] `perjob_ppinit`.** rocket re-runs `pp_state_init` per
   job; vendor runs state_init once at probe / on reset. rocket writes MORE, not
   less. Existing `perjob_ppinit=0` knob; low prior.

## Verdict
Code-level NPU register writes **match** — there is no writel the vendor makes on
a full inference that rocket lacks. The remaining difference is one-submit-PC-
iterates (regcmd content/HW) vs rocket's per-task CPU kicks, i.e. **go to the
live trace** (Part 2) to make the one-vs-many-submit / ordering difference
concrete, and treat candidate #1 (mesa regcmd layout for PC auto-advance) as the
real whole-graph path, with #2 (per-task ping-pong POINTER) as the cheap
seq-kick experiment.

## Part 2 — live writel trace (built, not flashed)
- `rknpu.wtrace=1` (vendor) and `rocket.wtrace=1` (open) each emit
  `… wt <seq> <abs_off> <val> <caller>` for every NPU register write; writing the
  param resets the sequence; capped at 20000 lines. Same absolute offsets on both
  stacks → directly diffable.
- `vendor-capture/diff_writel_trace.py VENDOR.log ROCKET.log` aligns the two by
  offset sequence, drops the vendor capture-build instrumentation, and prints
  vendor-only / rocket-only writes + a per-register multiset summary + verdict.
- Both kernels compile clean (aarch64): rknpu_drv.o, rknpu_job.o, rocket_core.o,
  rocket_job.o.
