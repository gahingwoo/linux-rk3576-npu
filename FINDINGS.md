# RK3576 NPU (rocket + Mesa Teflon) — conv0 zero-output: complete findings

## 2026-07-05 (BARE task_number=N CONFIRMED — native HW iteration (no busy-poll, no driver intervention) is BYTE-IDENTICAL to Phase B: chained CMAC still empty. NPU-software surface EXHAUSTED. Firmware RULED OUT (user boots the VENDOR SPI firmware — Rockchip TF-A + OP-TEE — under the mainline buildroot image, so BL31/BL32/OP-TEE is the SAME as the vendor, not the cause). Remaining dimension = the kernel's NON-NPU register spaces (GRF/CRU/power/syscon) that the NPU-block writel audit structurally missed, + mesa.)

Board, rocket.bare_tasknum (branch rk3576-bare-tasknum be86a968a): skip the per-run cnalive busy-poll so the
PC iterates task_number=N natively with ZERO driver register access during the run. Run A (busy-poll) vs
B (bare):
- **A == B, byte-identical.** conv0 distinct=240/241 REAL; task1/2 all 0x80; task3/4 distinct=3 {0d,7f,80};
  task5 distinct=2 nz=896; task6..28 all 0x00. Stripping the busy-poll changed NOTHING.
- `rocket bare: TASK_STATUS=6 top_wt_rd=332 core_wt_rd=0 top_dt_rd=110208` — chained weights AND inputs
  DMA'd to CBUF (top_wt_rd grew past conv0's ~36; top_dt_rd=110208), PC walked 6 tasks, yet chained CMAC
  empty. (core wt_rd=0 is NORMAL, not the oracle.)
- **VERDICT: bare native HW iteration does NOT self-arm the CSC on rocket.** rocket now runs the vendor's
  EXACT dispatch mechanism (byte-matched trailer + native task_number=N iteration + no per-task intervention
  + operands staged into CBUF) and the chained CMAC is still empty — so the rocket-vs-vendor gap is NOT in
  the NPU software (registers/regcmd/dispatch/init all matched AND now exercised in the vendor's own mode).
- **Firmware RULED OUT (new fact from the user):** the board boots the vendor's SPI firmware (Rockchip TF-A
  + OP-TEE) under the mainline buildroot rootfs -> the secure/firmware side is IDENTICAL to the vendor's, so
  a BL31/BL32/OP-TEE-SMC difference is NOT the cause. Supersedes the earlier "mesa=mainline TF-A/no OP-TEE"
  firmware lead as the explanation.
- **Remaining dimension (the one the audit structurally missed):** the writel audit covered ONLY the NPU
  register block (0x2770_xxxx). It did NOT cover GRF / CRU / power-domain / PVTPLL / memory-repair /
  syscon-regmap. RK SoCs commonly place NPU mode/repair/PVTPLL/enable bits in GRF, not the NPU block. A GRF
  (or CRU/power) bit the vendor sets that rocket + the DTS don't would look EXACTLY like this. Being chased
  (read-only enumeration of vendor rknpu's regmap/GRF/CRU/power writes vs rocket + DTS). [[project-rk3576-no-writel-gap]]
  [[project-rk3576-firmware-bl31-bl32]]

## 2026-07-05 (SESSION CLOSE-OUT — dispatch/iteration half SOLVED (upstreamable); wall localized to the CBUF->CSC->CMAC cold-start consume-arm; full software-lever ledger; per-task CSC-rearm (PP_CLEAR) CLOSED. Software surface exhausted -> RTL, with ONE standing software question (bare task_number=N).)

**WHAT IS NOW SOLVED (dispatch/iteration half — all confirmed working end-to-end, upstreamable):**
- Whole-graph trailer grammar: absolute next-pointer (PC 0x10 = next task's iova) + PC 0x14 amount + SYNC
  0x41 + broadcast OP_EN 0x1d, order [0x10][0x14][SYNC][broadcast], last task terminates 0/0 —
  runtime-confirmed byte-for-byte vs the vendor (task_number=8 dump == compile-time .rknn).
- The mesa rkt_pack_graph_regcmd fix emitting that grammar (key the trailer on ANY in-stream OP_EN —
  broadcast for conv0's firstconv fill OR the 4 per-unit OP_ENs the dw/pw normal fill emits — else only
  conv0 got a next-pointer and the chain broke after 1 hop).
- PC self-iteration via the trailer: trailer chain 29/29 (task0..27 match=YES, task28 LAST), TASK_STATUS
  walks the tasks.
- The TASK_CON upper-control-bit (0x6<<16 iterate-enable) — with it all 4 units engage (exec_ever=0xf, was
  0x8=RDMA-only); the earlier "internal wall" reading was the trailer packer bug, not this.
- Per-task engage + input DMA + weight DMA + per-task weight/CBUF config all correct (weight regcmd present
  per task, sensible sizes: conv0 0x600, depthwise 0x240, ... task28 1MB; DMA clean, RDERR=0/WRERR=0).

**THE REMAINING WALL (precisely localized):** CBUF->CSC->CMAC consume-arm. The chained CMAC never drains
CBUF -> empty accumulator -> requant zero-point. The task-6 stall is a SYMPTOM (CMAC doesn't drain -> CBUF
fills after ~6 layers -> PC can't stage layer 7). One coherent cause: the CSC consume/weight-load stage arms
only on the cold-start task — the mechanism-level, fully-cornered form of "only the cold-start task MACs."
(NB core wt_rd=0 is NORMAL, vendor too; not an oracle. The oracle is the zero-point output with data
confirmed in CBUF by the earlier CBUF audit.)

**SOFTWARE-LEVER LEDGER (tried against the consume-arm, result):**
- geom_all — forced every regcmd register into both PP groups -> no arm (regressed conv0).
- writel audit (vendor vs rocket, full driver enumeration + 1-task & 2-task captures) -> NO NPU register the
  vendor writes that rocket doesn't; descriptor-DMA falsified (task_number=2, base=0).
- pp_alt (alternate ping-pong PRODUCER pointer per task) -> reached the write path, not the MAC arm.
- Phase B trailer (runtime-exact vendor grammar) -> iteration + engage work, MAC still empty.
- per-task PP_CLEAR / CSC-rearm in the trailer -> did NOT reach CSC_WL; REGRESSED (chained tasks went fully
  inert 0x00 instead of writing zero-point 0x80). CLOSED.
- vendor per-task trailer contains NO re-arm entry to copy (S_POINTER 0x0e, no PP_CLEAR) -> its per-task
  re-arm is internal to the PC HW iteration.

**STANDING QUESTION (still open, NOT closed):** rocket has never actually run the vendor's bare
task_number=N HW-iteration mode (wg_continuous always wedged pre-trailer-fix, then was replaced by the
trailer-walk / seq-kick). Whether that bare mode self-arms the CSC is the one remaining software-side
question before committing fully to RTL. See CSC-CONSUME-REVIEW.md, WHOLEGRAPH-GRAMMAR.md.
[[project-rk3576-no-writel-gap]]

## 2026-07-05 (DISPATCH/ITERATION HALF CLOSED — trailer chain 29/29 perfect, weight regcmd present+plausible every task, all 4 units engage, DMA clean; YET chained CMAC empty. The wall is now precisely localized to ONE stage: CBUF->CSC->CMAC consumption. Converges with the earlier CBUF audit. The task-6 stall is a SYMPTOM: CMAC doesn't drain CBUF -> operands pile up -> the fixed CBUF fills after ~6 layers -> PC can't stage layer 7.)

Board, whole-graph one-submit, mesa Phase B fix + kernel trlchk-all-tasks (branch rk3576-weightfetch
5c9925792). The all-task trailer + weight dump settles both open questions:
- **Trailer chain PERFECT end-to-end (29/29):** task0..27 match=YES (pc10 == the next task's regcmd iova
  exactly), task28 match=LAST (pc10=0 terminator), sync=1 bcast=1 on EVERY task. So the task-6 stall is NOT
  a chain break -- the chain is intact all the way.
- **Weight regcmd PRESENT + PLAUSIBLE every task:** each has a real weight addr (0x1110) + byte-count
  (0x101c) with sensible per-layer sizes -- conv0 wtsz=0x600 (1536), depthwise wtsz=0x240 (576 = 9*64, the
  dw signature), pointwise/conv 0x2000/0x4000/0x8000..., task28 0x100000 (1 MB). NOT missing, NOT zero =>
  NOT a mesa weight-regcmd bug. (cbuf CBUF_CON0 0x1040 also set: 0x10000000 / 0x14000000 per task.)
- **VERDICT -- dispatch/iteration half is CLOSED and CORRECT:** trailer grammar, PC self-iteration, per-task
  engage (exec_ever=0xf all 4 units), input DMA, weight DMA, and per-task weight+CBUF config are ALL
  confirmed working/correct, reproduced end-to-end in a single whole-graph submit. The remaining wall is one
  specific pipeline stage: **CBUF->CSC->CMAC consumption** -- the operands reach CBUF (earlier CBUF audit
  proved data lands in CBUF) but the CMAC never drains/consumes them, so every chained layer outputs
  zero-point. Same stage the earlier CBUF audit fingered, now cornered with everything upstream eliminated.
- **task-6 stall = a SYMPTOM of the same cause, not a separate bug:** if the CMAC doesn't drain CBUF, each
  layer's staged operands accumulate in the fixed on-chip CBUF -> it fills after ~6 layers -> the PC can't
  stage the 7th -> stalls (PC_DONE fired fast, ~10 ms, not a poll-cap timeout). One coherent root: the CSC
  consume/weight-load stage arms only on the cold-start task (the mechanism-level form of the long-standing
  "only cold-start MACs" / "input reads but weights don't" wall). Next: attack the CBUF->CSC->CMAC stage
  directly; review (rk3576-weightfetch report) whether the CSC consume/drain trigger was ever touched vs
  only the CBUF-side staging/reset. [[project-rk3576-no-writel-gap]]

## 2026-07-05 (PHASE B TRAILER FIX — REVERSES the premature "internal wall" verdict. The mesa packer keyed the trailer on the broadcast OP_EN (0x81/0x08), which ONLY conv0's firstconv fill emits; the dw/pw normal fill emits 4 PER-UNIT OP_ENs by default -> only conv0 got a next-pointer -> the chain broke after 1 hop. Fixed to key on ANY in-stream OP_EN. Board: trlchk all match=YES, exec_ever=0xf (all 4 units engage, was 0x8), PC walks 6 tasks (TASK_STATUS=6, was 1), dt_rd=110208, RDERR=0/WRERR=0, clean PC_DONE. Trailer + iteration CONFIRMED WORKING. Remaining wall is NARROW: chained outputs still zero-point (empty accumulator) despite all units engaging + reading input. NB the reversal was the TRAILER FIX, not TASK_CON (that confound was refuted analytically, never built). **CORRECTION (metric discipline): my first read "core wt_rd=0 = chained fetch no weights" was WRONG -- core wt_rd=0 is NORMAL (vendor capture too: top[wt_rd=36] core[wt_rd=0]); weights count in TOP wt_rd (=332 here, cumulative, grew beyond conv0's ~36 so it can't prove chained fetch nothing). Real remaining wall = the earlier "operands don't reach the CMAC from CBUF, independent of content" (CBUF->CSC->CMAC staging), now in a working whole-graph walk. The rk3576-weightfetch diagnostic checks the per-task weight regcmd + the trailer past task 2.**)

Board, whole-graph one-submit, mesa Phase B FIX (branch rk3576-wholegraph-trailer 8ff472f) + kernel
rocket.trailer_check=1 (branch rk3576-trailer-check 3b48f285b).
- **Root cause of the earlier 1-hop stall = a mesa packer bug, NOT the HW wall.** The packer located the
  per-task trailer by scanning for the broadcast OP_EN (tgt 0x81 reg 0x08). But only conv0 uses the
  firstconv fill (which emits the broadcast); every dw/pw uses the normal fill, which by DEFAULT emits FOUR
  per-unit OP_ENs (CNA 0x1008/CORE 0x3008/DPU 0x4008/RDMA 0x5008), no broadcast. So the scan matched conv0
  only -> only conv0 got a next-pointer -> board trlchk task0 match=YES, task1+ NO-PC10 -> the PC walked one
  hop and stalled. Fix: key the trailer on ANY in-stream OP_EN (broadcast OR per-unit), so every task gets
  [0x10 abs next][0x14 amount][SYNC][broadcast].
- **After the fix (board):** trlchk task0/1/2 all match=YES (next-ptr == next task's iova). exec_ever=0xf
  (CNA+CORE+DPU+RDMA all engage on chained tasks, was 0x8=RDMA-only). PC walks to TASK_STATUS=6 (was ~1).
  top dt_rd=110208 (many layers' input read), core dt_wr=100464, RDERR=0 WRERR=0, PC_DONE fired ~10 ms
  (fast, not a poll-cap timeout). So the trailer + PC self-iteration + per-task engage are CONFIRMED WORKING
  -- the earlier "internal wall" verdict was premature (it was the packer bug).
- **Remaining wall (narrow):** chained outputs still zero-point -- conv0 distinct=243 REAL; task1 distinct=1
  all 0x80; task2 0x80; task3/4 distinct=3 {0d,7f,80}; task5 partial -- empty accumulator despite all units
  engaging + reading input.
- **CORRECTION (metric discipline, my misread):** I first called `core wt_rd=0` the oracle for "chained
  fetch no weights." WRONG -- core wt_rd=0 is NORMAL: the vendor's own est capture reads top[wt_rd=36]
  core[wt_rd=0] (weights count in TOP wt_rd, not core). Our run top wt_rd=332 is CUMULATIVE and grew beyond
  conv0's ~36, so it cannot prove chained layers fetch nothing. So "no weight fetch" is UNPROVEN. The actual
  earlier localization (single-task work, [[project-rk3576-conv0-weightlayout]] / [[project-rk3576-dispatch-step2]])
  was **"the CMAC operands (weights and/or input) do NOT reach the CMAC from CBUF, INDEPENDENT of weight
  content"** -- a CBUF->CSC->CMAC staging issue, not a weight-DMA or weight-value bug. That is the same wall,
  now reproduced inside a working whole-graph walk.
- **Two open sub-questions:** (a) whether the chained weight regcmd (CNA 0x1110 addr / 0x101c size) is even
  present + plausible per task (the diagnostic checks this) vs the operands staging into CBUF but not
  reaching the CMAC; (b) why the PC stops at task 6 not 29 (fast PC_DONE, not a timeout) -- possibly the
  trailer breaks past task 2 (trlchk only checked 0-2) or a downstream stall. Being chased (branch
  rk3576-weightfetch): extend trlchk to ALL tasks + dump per-task weight regcmd. See WHOLEGRAPH-GRAMMAR.md.

## 2026-07-05 (PHASE B board result — the runtime-exact trailer makes the PC self-iterate ONE hop (dt_rd=29792 = conv0+task1, TASK_STATUS 0->2, task1 engages+reads+writes) but task1's MAC is EMPTY (output all 0x80 = requant zero-point) and the PC stalls after ~1 task (task2+ untouched, 0x00). Matches the earlier ROCKET_NEXTPTR one-hop result; the exact trailer (broadcast+SYNC+abs-ptr) did not advance further. NOT yet "#1 closed": a TASK_CON latch CONFOUND is flagged — kernel WROTE PC TASK_CON=0x0007001d but the readback = 0x0001001d (the 0x6<<16 iterate-control bits absent). Resolving whether those bits latch (post-exec clear vs real write-failure) BEFORE any RTL verdict.)

Board, whole-graph one-submit (mesa Phase B branch rk3576-wholegraph-trailer 1233c5f: emit the vendor
trailer [PC 0x10 abs next][PC 0x14 amount][SYNC 0x41][BROADCAST OP_EN 0x1d] per task) + kernel
rocket.wg_continuous=1 + zero_out_bos=1. task_count=29, ONE submit (TASK_CON=0x…001d, DATA_ADDR=0xfe22c000,
DATA_AMOUNT=0x49).
- **Trailer advanced the PC (old wg_continuous wedged at task 0):** top dt_rd=29792 = conv0 (9408) + task1
  (20384) input BOTH read; TASK_STATUS 0->2; task1 engaged, read its input, and WROTE its output.
- **But chained MAC still EMPTY (zero_out_bos oracle):** conv0 (task0) distinct=240 min00maxff REAL; task1
  distinct=1 all 0x80 (WROTE, but zero-point = empty accumulator); task2..28 distinct=1 all 0x00 (untouched,
  PC stalled after ~1 hop, PC_DONE fired ~9ms, samples=1). No chained task computed a real feature map.
- Same "only cold-start task MACs" wall; trailer solved ITERATION (advance) not the chained-MAC arm.
  Reproduces the earlier ROCKET_NEXTPTR one-hop-then-stall; the runtime-exact additions (kept broadcast,
  SYNC, absolute next-ptr) did not improve on it.
- **CONFOUND before the RTL verdict:** TASK_CON write 0x0007001d vs readback 0x0001001d (only bit16 present,
  the 0x6<<16 control bits gone). If 0x6<<16 is the "iterate N tasks" enable and it did not latch, the PC
  may be 1-shot-committing, not N-walking -> Phase B never truly tested vendor-grammar iteration and the
  1-hop-empty result is a control-bit artifact, NOT proof of an internal arm wall. Being resolved (branch
  rk3576-taskcon-latch): 3-point TASK_CON readback (before OP_EN / after OP_EN / at completion) + vendor
  TASK_CON write-path diff. Same class of confound as the earlier "broadcast restarts the PC" (a mis-set
  next-pointer). #1 is NOT closed until this is cleared.

## 2026-07-05 (WHOLE-GRAPH GRAMMAR runtime-CONFIRMED — GO on Phase B (mesa). A runtime dump of the vendor's task_number=8 submit buffer EXACTLY matches the compile-time .rknn (librknnrt does NOT rewrite the trailer): each task ends with a self-iteration trailer [PC 0x10 = ABSOLUTE next regcmd_addr][PC 0x14 = 0x47 amount][SYNC 0x41][BROADCAST OP_EN 0x81/0x08 = 0x1d]. mesa RK3576 whole-graph deviates on all three; Phase B copies the confirmed grammar.)

Board, vendor kernel + rknpu.trailer_dump=1 (branch rk3576-runtime-trailer 4daa62ae1), whole-graph chain
(task_number=8, task_base_addr=0x0). Dumped the first 3 tasks' trailer (read PAST regcfg_amount where the
+4 EXTRA lives). Three VERDICT lines:
- **OP_EN = BROADCAST** (tgt 0x81 reg 0x08 = 0x1d), NOT per-unit -- every task. Settles the biggest mesa
  deviation (the RK3576 packer replaces the broadcast with 4 per-unit OP_ENs).
- **PC 0x10 next-pointer = ABSOLUTE**: T0 0x10 = 0xffff7980 == T1's regcmd_addr exactly; T1 -> 0xffff7e00
  (T2), T2 -> 0xffff8280 (T3). librknnrt patches it to the absolute iova at load. (mesa ROCKET_NEXTPTR math
  = graph_addr + (g+1)*stride already yields this.) PC 0x14 = 0x47 = pc_data_amount.
- **SYNC 0x41 present** at trailer position [141]; order [0x10][0x14][SYNC][broadcast].
- Structure confirmed: each task = 139 config [0..138] + 4 trailer [139..142] + pad [143], 0x480 (=144 u64)
  contiguous stride; T0..T3 regcmd_addr = 0xffff7500/7980/7e00/8280.
- **The mesa "broadcast 0x08 RESTARTS the PC" note was a CONFOUND**: broadcast re-fires with PC 0x10 still
  pointing at the CURRENT task (no next-pointer) -> re-runs the same task -> looks like a restart. With the
  absolute next-pointer written BEFORE the broadcast, it commits-and-advances. Order is load-bearing.
- **GO, runtime-confirmed** (upgrades the earlier compile-time GO). Phase B (mesa rkt_pack_graph_regcmd):
  emit per task [139 config][PC 0x10 abs next = graph_base+(g+1)*stride][PC 0x14 amount][SYNC 0x41][BROADCAST
  0x1d], last task next-ptr = 0; drop the per-unit substitution; kernel unchanged (task_number=N stop-count).
  See WHOLEGRAPH-GRAMMAR.md. [[project-rk3576-no-writel-gap]]

## 2026-07-05 (pp_alt (candidate #2) CLOSED — alternating the seq-kick producer ping-pong group does NOT arm any chained-layer MAC. Board, seq-kick+warm-chain, clean output-distinct oracle: conv0 real / every chained task empty in BOTH pp_alt=0 and =1. Confirmed TRUE NEGATIVE, not a no-op: pp_alt=1 flipped task1's output from untouched 0x00 to written zero-point 0x80 — the regcmd patch reached HW and moved the WRITE path, but the MAC accumulator stays empty. The arm is below the register/config level, as geom_both + pure-position already implied.)

Board (branch rk3576-pp-pointer a75db5cdc, LOCAL; rocket.pp_alt): the seq-kick producer S_POINTER POINTER
is hardcoded 0 every kick; pp_alt alternates it by per-job task index (task 0 -> group 0 control unchanged,
odd -> group 1), patching the regcmd's own CNA 0x1004 / CORE 0x3004 entries in DRAM too (the driver write
alone is overwritten mid-run by those entries). S98mndump ran the pp_alt=0 baseline; pp_alt=1 over serial.
- **Every chained task empty in BOTH modes (output-distinct oracle, NOT dt_wr).** pp_alt=0: conv0 (task0)
  distinct=240 min00 maxff REAL, task1 distinct=1 all-0x00, task2..28 distinct<=3 (zero-point). pp_alt=1:
  conv0 distinct=241 REAL, task1 distinct=1 all-**0x80**, task2..28 distinct<=3. No task>=1 ever reaches a
  real feature map (the lone distinct=3 is task3's {0d,7f,80} = zero-point +/-1, present identically in
  both runs). Every task engages (cna_eng=1 core_eng=1) in both.
- **TRUE NEGATIVE, not "didn't take effect."** The pp lines show prod correctly alternating (task odd
  prod=1, even prod=0, task0 prod=0), and task1's output BO flipped from baseline `0x00 nz=0/4096`
  (untouched) to pp_alt=1 `0x80 nz=4096/4096` (written full zero-point). So the regcmd patch DID reach the
  hardware and changed the DPU write path -- but the accumulator is still empty (empty MAC -> requant ->
  zero-point 0x80). Group alternation touches the pipeline, not the MAC arm.
- **CLOSED.** Consistent with geom_both (config in BOTH groups didn't arm dw1) and pure position ("only
  task 0 computes" is inconsistent with a stuck-producer/advancing-consumer story, which predicts 0/2/4).
  Directly measured now. NOTE (reusable): the consumer group is NOT a readable index -- CNA/CORE S_POINTER
  bit0 = producer echo, bit16 = executer engage-status; exec_ever + the output-distinct oracle are the real
  signals, not a consumer-group read, and dt_wr counts zero-point writes so it is not a clean compute
  oracle. The only lever left is #1 (mesa regcmd laid out for the PC's own task auto-advance = the vendor
  whole-graph grammar), which is a mesa change, not a kernel one.

## 2026-07-04 (WRITEL AUDIT — complete static enumeration of EVERY NPU register write, both drivers, across a FULL inference: NO writel the vendor makes that rocket does not. task_base_addr=0 even for task_number=2 REFUTES the descriptor-DMA idea. The difference is grammar (one submit / PC iterates N vs seq-kick N kicks), not a missing register. Live writel-trace built into both stacks for the decisive runtime diff. See WRITEL-AUDIT.md.)

Part 1 (read-only) enumerated every NPU-register writel in the vendor rknpu driver (rk3576-vendor-kernel/
drivers/rknpu/, RK3576 config) across ALL functions, and every write in rocket's default path, then diffed
against BOTH captured vendor logs. **Decisive facts:**
- **task_base_addr=0 even for task_number=2.** dirty/vendor.txt holds a real MULTI-task vendor capture:
  `SUBMIT task_number=2 ... task_con=0x70002 task_base_addr=0x0 pc_dma_ctrl=1`. The vendor iterates 2 tasks
  from ONE submit with PC_DMA_BASE_ADDR(0x34)=0. This **kills the descriptor-DMA dispatch theory** outright
  (the prior "descriptor experiment was wrong" note rested on a single-task capture; now the multi-task one
  confirms it directly). rocket writes 0x34=0 too -> not a gap. Do NOT re-explore PC_DMA_BASE_ADDR.
- **The per-submit register sequence is identical** (reconfirmed vs 1-task vendor-live-cap.txt AND 2-task
  dirty/vendor.txt). Vendor RK3576 NPU writes, complete set: state_init (probe/reset: 0x10=1, 0x1004 toggle
  0/1/0x1e, 0x1024=0x80000000 x2); per submit (subcore_commit+commit_pc): 0x10=1(slave), 0x1004=0xe,
  0x3004=0xe (num_irqs=2>1), 0x10=regcmd, 0x14=amount, 0x20=0x300, 0x24=0x300, 0x30=((0x6|pp)<<16)|N,
  0x34=task_base_addr(=0), 0x8=1, 0x8=0; per IRQ: 0x24=0x1ffff; perf clear 0x2210/0x2410. NO other NPU
  write anywhere -- the action ioctl exposes no register write, bw_priority disabled on RK3576
  (bw_priority_addr=0), NO register-BAR mmap, power/clk via frameworks, NBUF via IOMMU map not writel.
- **VERDICT: no register offset the vendor writes and rocket never does.** The only multiset differences are
  rocket writing MORE (per-job pp_state_init; 0x24 also clearing PC_DONE). The vendor's sole advantage is
  STRUCTURAL: one submit + task_number=N, PC hardware iterates all N tasks from one OP_EN (ping-pong group
  advances in HW; next task's regcmd found from the regcmd stream since base=0). Not a kernel writel.
- **Ranked candidates:** #1 [mesa, NOT kernel] regcmd not laid out for PC auto-advance -- vendor whole graph
  is one task_number=N submit, PC strides via regcmd stream + the +4 EXTRA amount stride; mesa emits the
  next-pointer/contiguous layout only for soc!=RK3576. This is wg_continuous's wedge. #2 [kernel, cheap,
  maybe untested cleanly] seq-kick's ping-pong POINTER never advances -- rocket hardcodes pp_pointer=0 every
  kick (pp_task_idx++ computed but unused); try POINTER=pp_task_idx&1 (weak counter-indication: geom_both
  forced config into both groups, not the executer's per-task active-group select). #3 perjob_ppinit (rocket
  writes MORE not less; low prior).
- **Part 2 (built, NOT flashed):** rknpu.wtrace / rocket.wtrace log `... wt <seq> <abs_off> <val> <caller>`
  for every NPU write (same absolute offsets both stacks; reset-on-arm; capped 20000). Differ:
  vendor-capture/diff_writel_trace.py aligns by offset seq, drops the vendor capture-build instrumentation,
  prints vendor-only/rocket-only + per-register counts + verdict (self-tested). Branch rk3576-writel-trace,
  LOCAL: vendor 763eae8c8, rocket b60af5ebf; both compile clean aarch64 (rknpu_drv/job.o, rocket_core/job.o).
  Report+differ pushed to linux-rk3576-npu main 9e6e794. Next: flash, capture both, run differ -- if it
  prints nothing (static read predicts so) the search leaves the register file for the one-vs-many-submit
  grammar (mesa regcmd chaining), or test cheap candidate #2.

## 2026-07-04 (LOOSE END CLOSED — zero_out_bos (stale-proof) confirms chained layers write NOTHING real and dt_wr is a cumulative counter. conv0 writes a genuine feature map (distinct=232) to its own pre-zeroed BO; dw1/task2/task3 are distinct<=2 (EMPTY/ZEROPOINT) in every dump with zeroing on. The software-structural line is cleanly closed: the wall is below the registers, only the cold-start task MACs.)

Board, seq-kick + warm-chain, rocket.zero_out_bos=1 (kernel branch rk3576-bo-groundtruth a3c67f7c1: memset
every output BO to 0 + flush before the job kicks; per-completion readback + a finalize whole-BO classify;
per-completion core dt_wr delta). The zeroing removes the conv0_twice stale-data trap: any post-run
non-zero is a definitive write this run.
- **dt_wr is CUMULATIVE.** Per-completion core dt_wr deltas: conv0=25088, dw1=+20160, task2=+4928, ...
  (25088, 45248, 50176, ...). Running totals, not per-kick output sizes -- the "large early dt_wr" that
  nagged the open_high result is a cumulative-counter artifact, now settled.
- **Chained layers write NOTHING real (stale-proof).** With the BOs pre-zeroed, the per-completion readback
  reads: dw1 (0xfea69000) distinct=1 every dump (some min=80 = zero-point); task2 distinct<=2; task3
  distinct<=3 (min0d max80, still zero-point-ish). No chained output is a real feature map, and none holds
  mis-routed real data. Outcome (1)/(2), NOT the reversal (3).
- **conv0's real output is GENUINE, not stale.** conv0 (0xfeb2d000) reads distinct=232 (min00 max ff) in a
  BO that was zeroed immediately before the run -> conv0 truly wrote it this run. (conv0 also reads
  distinct=1 in the warm inferences, definitively empty -- consistent with cold-start-only.)
- **Self-correction on the diagnostic:** my finalize whole-BO groundtruth block read conv0 EMPTY and I
  first misread that as "conv0 doesn't land." It was an artifact: each inference runs a main job + a tiny
  tail job, and zero_out_bos runs PER JOB, so the tail job re-zeroed bo0 AFTER the main job's conv0 wrote
  it, and the finalize scan (running in the tail job) saw bo0 zeroed. The per-completion readback -- which
  catches conv0's 232 mid-run -- is the truth. The zeroing worked; only the per-job placement of the
  finalize scan was wrong (harmless, diagnostic-only).
- **Landing:** every stale-data confound is now removed and the conclusion holds byte-for-byte: only the
  first task after NPU-init writes a real feature map; every chained layer's output is definitively empty.
  Combined with the byte-identical per-kick register sequence, the matched completion handshake, the
  refuted OP_EN-high timing, and geom_all (no regcmd register is the arm), the RK3588->RK3576
  software-structural line is exhausted. The switch that arms the CMAC for the cold-start task and only it
  is below the last writable register -- NVDLA CSC/CMAC sequencer state / an RK3576 quirk, not a driver fix.

## 2026-07-04 (open_high (OP_EN-high, upstream RK3588 model) REFUTED — dw1's output BO is distinct=1 in BOTH open_high=0 and =1, no completion timeout. The last per-kick structural difference from RK3588 did not arm the chained layer. CAVEAT/loose-end: the per-completion core dt_wr counters show large early values (25088->45248->50176->90944->100352) that don't square with "only conv0 computes"; core dt_rd is clearly cumulative, so dt_wr is likely a cumulative/dirty-counter artifact, but this isn't 100% nailed. open_high shifted the collapse point by one completion (A idle at #6, B does one more real read+write).)

Board A/B, seq-kick + warm-chain, rocket.open_high (kernel branch rk3576-openhigh 5f404abb8: drop the
submit OP_EN=0 pulse, leave OP_EN high through execution, complete on DPU-done bits 8/9; unconditional
300 ms poll cap). RUN A open_high=0 vs RUN B open_high=1:
- **dw1 (task=1) output BO 0xfea69000 = distinct=1 in BOTH A and B** (all 0x00 or all 0x80 zero-point).
  The all-tasks readback -- the direct read of dw1's declared output -- is empty either way. **open_high
  did not unlock the chained layer.** No "seq-kick poll TIMEOUT" fired (completion worked; the DPU-done
  path/poll completed within the cap), so the poll-cap safety net held without engaging.
- **Verdict: the OP_EN-high (upstream) model is refuted as the per-task arm.** Together with the
  byte-identical per-kick register sequence and the already-matching completion handshake, the RK3588 ->
  RK3576 software-structural per-kick line is essentially exhausted.
- **CAVEAT (unresolved):** per-completion core dt_wr = 25088, 25088, 45248, 50176, 90944, then 63... (A)
  / ...100352 then 63 (B). Large values for the first ~5-6 completions. core dt_rd is unmistakably
  cumulative (91,178,265,372,... resets at inference boundaries), so core dt_wr is most likely also a
  cumulative/uncleared counter, not a per-kick output size -- in which case the readback (dw1 empty) is
  the truth. But if dt_wr were per-kick it would mean the early layers write substantial data somewhere
  other than their readback'd output BO, which would overturn "only conv0 computes". Not double-handling
  (consecutive done-lines are ~12 ms apart, 132 completions ~= 4-5 inferences x 29 tasks). A vs B diverge
  only at completion 6 (A top_rd=64/dt_wr=63, B top_rd=4704/dt_wr=100352) -- open_high pushed the real-work
  run one completion further before collapsing, but no output BO became non-empty.
- **NEXT: nail the dt_wr caveat before declaring the software line closed -- zero each task's output BO
  before its kick and widen the readback beyond the first page, to see whether any early layer writes real
  data anywhere. If all still empty -> cleanly pivot below software (NVDLA CSC/CMAC RTL / RK3576 quirk); if
  an early layer writes real data elsewhere -> that reopens the whole model.**

## 2026-07-04 (conv0_twice CONFIRMS pure position — even conv0's OWN regcmd + external input does NOT MAC when re-run as a non-cold-start kick. The 2nd conv0 (30th kick) has core dt_wr=63 (vs 25088 real) and top dt_rd=0; its output BO's distinct=245 was STALE 1st-run data, not a recompute. distinct is not the oracle, dt_wr is. Only the first task after NPU-init MACs, independent of layer/data/input-source.)

Board (seq-kick + warm-chain, rocket.conv0_twice=1, kernel branch rk3576-arm-hunt 66245517d+18f01a896:
re-run task 0 after the job completes, no reset, then finalise). Per inference the log shows
"rocket conv0_twice: re-running task 0" then the replay's completion:
- **1st conv0 (cold-start):** core dt_wr=**25088**, top dt_rd=9408 wt_rd=96 -> real MAC.
- **2nd conv0 (replay, ~30th kick):** core dt_wr=**63**, top dt_rd=**0** -> did NOT DMA its input and wrote
  essentially nothing. Its output BO still read distinct=245 with byte-identical first bytes
  (b7 7f ea e5 ...) to the 1st run = STALE, never overwritten. **The 2nd conv0 did NOT compute.**
- **VERDICT: PURE POSITION, confirmed and now directly measured.** conv0's exact regcmd + the same external
  input, run as a non-first-after-init kick, produces no MAC. So the gate is NOT layer type, NOT data, NOT
  input source -- it is task position: only the first task the PC executes after NPU (re)init arms the CMAC.
- **Metric-discipline note (again):** the 2nd conv0's distinct=245 first read as "it computes" (which would
  have REFUTED position); the perf counter (core dt_wr=63 vs 25088, top dt_rd=0) corrected it to "stale,
  empty". distinct/first-bytes are not a correctness oracle for a re-used BO; core dt_wr is.
- **Ties to the Part 1 #1 hypothesis:** the 2nd conv0 has top dt_rd=0 (even more inert than dw1's 20384) --
  a non-first kick's whole CNA->CBUF->CMAC path fails to arm, consistent with "only the first kick's OP_EN
  (left-high vs our submit-pulse) actually arms the pipeline".
- **NEXT: add a poll cap to the seq-kick completion (so OP_EN-high can't hang -> reset -> iommu death),
  then test Part 1 #1 (leave OP_EN high through execution, upstream-style) -- the top adaptable difference.**

## 2026-07-04 (RK3588-vs-RK3576 task-2+ diff (read-only, upstream pristine rocket at e7d700e14). The per-task register sequence is byte-IDENTICAL to upstream, and our completion handshake already matches/exceeds it. The ONLY per-kick deviation is the seq-kick macro's extra OP_EN=0 pulse AT SUBMIT (upstream leaves OP_EN high during execution). Ranked below. Built the safe conv0_twice position-confirmation knob; did NOT build the OP_EN-high variant (risks an uncapped poll->hang->reset->iommu-death).)

Diffed the pristine upstream RK3588 rocket (linux-next import e7d700e14, 635 lines) against our RK3576
rocket_job.c, the task-2+ path specifically. geom_all already closed the regcmd-register line (see below);
this pins what STRUCTURALLY differs from the WORKING RK3588 path.

- **upstream RK3588 hw_submit (per task, WORKS):** reset check; task=tasks[idx]; idx++; BASE_ADDRESS=0x1;
  CNA S_POINTER = PP_EN|EXECUTER_PP_EN|PP_MODE|extra_bit (0x0e for core 0); CORE S_POINTER same;
  BASE_ADDRESS=task->regcmd; REGISTER_AMOUNTS; INT_MASK=DPU_0|DPU_1 (0x300); INT_CLEAR=DPU_0|DPU_1;
  TASK_CON=RESERVED_0|TASK_COUNT_CLEAR|TASK_NUMBER(1)|TASK_PP_EN; TASK_DMA_BASE_ADDR=0; **OP_EN=1 (only)**.
  Completion (DPU-done IRQ): **OP_EN=0; INT_CLEAR=0x1ffff**; re-kick next or finish. job_run: pm_get +
  iommu_attach + hw_submit -- NO reset/re-init (rocket_core_reset is error-path only).
- **RANKED diff (task-2+ arming candidates):**
  1. **[TOP, concrete, but risky to test] submit-time OP_EN=0 pulse.** Our seq-kick macro pulses OP_EN
     1->0 AT SUBMIT (vendor single-shot style); upstream sets OP_EN=1 and leaves it HIGH through
     execution, clearing to 0 only at completion. For a per-task RE-KICK model (which upstream is and we
     are), the OP_EN=1->0 transition AT COMPLETION may be the HW's per-task commit/re-arm; pulsing at
     submit (OP_EN=0 during execution) skips it. The vendor's submit-pulse works only because the vendor
     uses PC HARDWARE ITERATION (task_number=N, one pulse, PC advances internally) -- not re-kick.
     Adaptation: drop the macro's OP_EN=0, leave OP_EN high, clear at completion (already done at the
     completion site). NOT BUILT: our seq-kick poll waits on PC_DONE with no cap, and PC_DONE may not
     assert while OP_EN is high -> infinite poll -> sched timeout -> rocket_core_reset -> shared rk_iommu
     dies. Needs a poll cap first; flag before flashing.
  2. **[weaker] pp_state_init per-job.** RK3576-only (rocket_core_pp_state_init: S_POINTER PP_CLEAR +
     DS1=0x80000000 to both PP groups). Upstream RK3588 runs it NEVER; vendor RK3576 runs it ONCE at
     probe; we run it at probe AND per-job (perjob_ppinit=1). warm_chain (skip on re-kicks, task 0 still
     gets it) already tested -> engage+DMA, no MAC, so a plain skip is not the fix -- but "only at probe,
     never per-job" (perjob_ppinit=0, matching vendor+upstream) is a distinct, untested config, testable
     with the existing knob and no new code. Risk: may break conv0 (probe-time state stale by inference).
  3. **[not it] completion handshake.** We already do OP_EN=0 + full INT_CLEAR=0x1ffff at completion
     before each re-kick (>= upstream). Matches; ruled out.
  4. **[not it] per-task register values.** Byte-identical to upstream (S_POINTER 0x0e, TASK_CON equiv,
     INT_MASK 0x300, OP_EN=1). Confirms geom_all -- no register value is the miss.
  5. **[not it, intra-job] job_run adds attach-once + tlb_flush** (per-job; a seq-kick graph is ONE job,
     so these don't fire between tasks). mesa: per-task regcmd byte-identical; the next-pointer trailer is
     only used in wg_continuous, not seq-kick.
- **Completion detection differs (poll PC_DONE vs upstream DPU-done IRQ) but the register actions match.**
- **NEXT: test #1 first (highest likelihood) but only after adding a poll cap so OP_EN-high can't hang;
  meanwhile conv0_twice (built, rk3576-arm-hunt 66245517d) gives a 1-flash pure-position verdict.**

## 2026-07-04 (geom_all CLOSES the regcmd-register line — the chained-layer CMAC arm is NOT any regcmd register. dw1 stays distinct=1 with the ENTIRE regcmd config (88 CNA + 8 CORE + 67 DPU + 20 RDMA) CPU-forced, and conv0 CRASHES to distinct=1 (uniform 0xfe). Not CBUF data, not any register -> it is a cold-start internal hardware context.)

Board A/B, seq-kick + warm-chain, rocket.geom_all=1 (kernel branch rk3576-geom-all 7cc4032e1: CPU-write
EVERY regcmd config target -- CNA/CORE into both PP groups + DPU/RDMA once via the driver's dpu_iomem/
dpu_rdma_iomem, skipping the 0x81/0xf008 broadcast and per-block S_POINTER/OP_EN). geom_all fired,
logging "wrote 88 CNA + 8 CORE (both groups) + 67 DPU + 20 RDMA regs (skipped 0 broadcast)" per task:
- **RUN A geom_all=0:** conv0 (task=0) distinct=240, dw1 (task=1) distinct=1. Baseline.
- **RUN B geom_all=1:** conv0 distinct=**1** (min=fe max=fe = uniform 0xfe -- geom_all's out-of-sequence
  DPU/RDMA writes wrecked conv0's compute), dw1 (task=1) distinct=**1** (unchanged).
- **Verdict:** CPU-forcing the ENTIRE regcmd config (CNA/CORE/DPU/RDMA, every block) does NOT make the
  chained layer compute, and it corrupts conv0 -- so the CPU writes reach the executer, yet no register
  value is the miss. **The chained-layer CMAC arm is NOT any regcmd register. The regcmd-register line is
  CLOSED.**
- **Where this leaves the three exclusions:** (1) not CBUF data (dw1's data reaches the CBUF); (2) not any
  regcmd register (CNA/CORE/DPU/RDMA all CPU-forced, dw1 still 0); (3) => the differentiator between conv0
  (cold-start) and dw1 (chained) is a **cold-start internal hardware CONTEXT** established only for the
  first task after NPU (re)init, not reproducible by any register write.
- **NEXT:** the remaining routes are structural, not register-level. (a) per-layer true cold-start (full
  NPU re-init/reset between layers) -- a minefield (rekick_reset=2 crashed, soft_reset irrelevant,
  force_powercycle hangs); (b) read the RK3588 open-rocket chained path (Tomeu's RK3588 runs int8
  MobileNet byte-correct, so its task 2+ DO compute) and find the one RK3576 delta -- the "adapt not RE"
  route, likely the most tractable.

## 2026-07-04 (CBUF audit_all pins the break at CBUF->CMAC, NOT CNA->CBUF. dw1's real data DOES reach the CBUF (6 windows changed PRE->POST, nz 714->1023) yet the CMAC outputs zero -> NBUF is RULED OUT, the break is downstream of CBUF staging. CBUF_CON live=0x44 identical for conv0 and dw1; the CNA rawor CSC bit is 0 for BOTH so it does not pin CSC.)

Board, seq-kick + warm-chain, rocket.audit_all=1 (per-task 16x64KB CBUF windows PRE/POST + changed-window
diff + CBUF_CON live/regcmd decode, kernel branch rk3576-cbuf-audit-alljobs 47b58df1d). Per-task snapshots
labelled by DPU-out iova (conv0=0xfeb2d000, dw1=0xfea69000):
- **dw1's data reaches the CBUF.** dw1 PRE (= conv0's leftover, 242/714 ...) -> POST 188/1023 192/1022 ...,
  POST changed[0x00000 0x10000 0x20000 0x30000 0x40000 0x50000] = SIX windows changed, nonzero rose
  ~714->~1023 (dense real data staged). conv0 stages too (changed[0x0..0x40000], 5 windows). **Both layers
  stage into CBUF; only conv0's is consumed by the CMAC. So CNA->CBUF is NOT the break -> NBUF RULED OUT
  -> the break is CBUF->CSC->CMAC (data present, not consumed).**
- **CBUF_CON does not differentiate.** live=0x00000044 for BOTH conv0 and dw1 (DBANK=4, WBANK=4) while the
  regcmd requests DBANK=0 for both (conv0 CON0=0x10000000, dw1 CON0=0x14000000; low 14 bits 0 both) -> the
  executer runs a default bank config the regcmd never latches (same PP-latch as geom_both), identical
  across layers. DATA_ENTRIES differ (conv0=15, dw1=56) as expected per layer size.
- **CORRECTION / caveat:** the CNA rawor CSC bit is 0 for conv0 (which COMPUTES) as well as dw1, so
  "CSC never fired" is NOT supported by rawor -- it does not pin the break. (conv0 rawor=0x30000000,
  dw1=0x20000008; the decoded FEAT/WT/CSC bits 0-5 are ~0 for both; dw1 has WT1=1, conv0 WT=0, which is
  the opposite of a "dw1 didn't load" story.)
- **NEXT:** the break is CBUF->CMAC. If the 64KB windows == the 16 CBUF banks, DBANK=4 => the CMAC reads
  bank 4 (window 0x40000), which BOTH layers changed -- so pin the exact bytes/offset the CMAC reads per
  (DBANK=4, DATA_ENTRIES): does dw1's staged data actually occupy the sub-range the CMAC walks, or does
  dw1's DENTRIES=56 layout leave the CMAC's read window empty? i.e. match "where the CNA wrote" against
  "where the CMAC reads" for dw1 vs conv0.

## 2026-07-04 (geom_both REFUTED as the dw1 miss — config-latch is NOT it. dw1 still distinct=1 with its config CPU-forced into both PP-groups, and conv0 even DEGRADED 239->111 (proving the CPU writes DO reach the executer). The wall is confirmed to be CNA->CBUF->CMAC data staging, not register geometry.)

Board A/B, seq-kick + warm-chain (the regime where dw1 reads dt_rd=20384), all-tasks readback. geom_both
fired (logged "wrote 96 CNA/CORE regs into both groups" per task):
- **RUN A geom_both=0:** task=0 (conv0) distinct=239, task=1 (dw1) distinct=1. Baseline wall.
- **RUN B geom_both=1:** task=0 distinct=**111** (still a real map, min00 maxff, but fewer values —
  geom_both's double-write perturbed conv0), task=1 (dw1) distinct=**1** (unchanged).
- **Verdict:** forcing dw1's real CNA/CORE config into BOTH ping-pong groups did NOT make dw1 compute,
  and it measurably CHANGED conv0's output (239->111) — so the CPU writes genuinely reach the executer
  (the config-latch premise holds), yet dw1 still MACs zero with its config present. **Config geometry is
  definitively NOT the dw1 miss.** dw1 reads its input (dt_rd=20384) and its weights (wt_rd=36); the only
  stage between the CNA DMA and the CMAC is the CBUF. So the break is CNA->CBUF (data DMA'd but not landed
  in the CBUF bank the CMAC reads) or CBUF->CSC->CMAC (data in CBUF but the CSC never reads it) — and only
  the cold-start task clears it. cbuf_reset knobs already DEAD.
- **NEXT (i):** diagnostic — dump conv0 vs dw1 CNA CBUF-config registers (cbuf entry/bank alloc) + any
  CSC/CMAC status, to pin the break at CNA->CBUF vs CBUF->CMAC before touching the big NBUF structural
  route (ii).

## 2026-07-04 (STAGE 2 — vendor rknpu init audit. RK3576 has two SoC-unique inits: (1) rk3576_state_init = CNA ping-pong dual-group prime (rocket DOES replicate as pp_state_init); (2) rk3576_cache_sgt_init + NBUF on-chip SRAM operand cache (rocket/mesa NEVER replicate). The diagnosed mechanism: the CMAC executer reads config from the CNA PP-groups; regcmd/PC writes don't reliably latch, only CPU writes do; geom_both ruled out config-geometry, leaving CNA->CBUF->CMAC data staging as the cold-start-only step. NEXT cheap shot: geom_both=1 in the new dw1-reads-input regime, never tested there.)

Audited `rk3576-vendor-kernel/drivers/rknpu` init + commit path against rocket.

**Vendor commit_pc (rknpu_job.c:448-720) is ONE submit; the PC hardware iterates task_number tasks.**
Per submit it writes: 0x10 PC_DATA_ADDR=first_task->regcmd_addr; 0x14 PC_DATA_AMOUNT; 0x20 INT_MASK;
0x30 PC_TASK_CON=((0x6|task_pp_en)<<bits)|task_number; **0x34 PC_DMA_BASE_ADDR=args->task_base_addr**
(rocket writes 0x34 = 0 — but conv0 computes with 0x34=0, so not the arming); 0x08 OP_EN 1 then 0. No
per-task software re-arm — the units are re-programmed from each task's regcmd as the PC strides.

**RK3576-unique inits (state_init/cache_sgt_init are non-NULL ONLY for rk3576; NULL for 356x/3588/etc):**
1. `rk3576_state_init` (drv.c:111): `0x10=1; 0x1004=0; 0x1024=0x80000000; 0x1004=1; 0x1024=0x80000000;
   0x1004=0x1e` = prime BOTH CNA ping-pong groups with the default DS1=0x80000000, leave POINTER=0x1e
   (PP_MODE|EXECUTER_PP_EN|PP_EN|PP_CLEAR). **rocket replicates this byte-for-byte in
   rocket_core_pp_state_init** — but rocket RE-RUNS it at the head of every job; the vendor runs it ONCE
   at probe / after reset.
2. `rk3576_cache_sgt_init` (drv.c:123) + NBUF: builds cache_sgt describing NBUF SRAM blocks
   (0x3fe80000, 1MB, 448/64/448/64 KB). rknpu_gem.c maps a BO flagged RKNPU_MEM_TRY_ALLOC_NBUF /
   RKNPU_CACHE_NBUF so its first nbuf_size bytes land in on-chip SRAM instead of DRAM (map_with_cache_sgt
   @422). **rocket/mesa never allocate a cache BO → the whole graph runs from DRAM.** Biggest structural
   gap, but conv0 (DRAM input) computing shows DRAM is not a hard requirement; NBUF-dependence of chained
   layers is unproven.

**Mechanism (from rocket's own accumulated comments, now joined to today's dw1-reads fact):** the CMAC
executer reads its CNA/CORE geometry from the active ping-pong group. regcmd writes driven by the PC do
NOT reliably latch to the group (both groups read back the pp_state_init default DS1=0x80000000); only
CPU writes latch. `geom_both` (CPU-replicate the regcmd's CNA/CORE config into both groups) was tried and
"ruled out the register geometry" — so the config VALUES are not the miss; the diagnosed racy part is the
**CNA->CBUF->CMAC data staging** (a warm/non-first task's CBUF holds stale/empty data). cbuf_reset knobs
= DEAD. This matches the cold-start wall: staging only works for the first task after a fresh
pp_state_init/CBUF; later tasks read their input (dt_rd=20384, new today) but the CBUF->CMAC step is empty.

**NEXT (cheap, no kernel rebuild — geom_both is already compiled in):** set rocket.geom_both=1 in the
CURRENT seq-kick/warm-chain regime and read dw1 (task=1) output. geom_both was only ever tested back when
dw1 didn't even read its input (config was moot then); with dw1 now reading real input, forcing its config
into the PP group is a fresh test. dw1 distinct>1 => config-latch was the miss; dw1 still 1 => confirmed
CBUF data-staging, pivot to CBUF/NBUF structural.

## 2026-07-04 (COHERENCY RULED OUT from existing logs — dw1's input probe reads conv0's REAL 244; no flash needed. The intermediate is NOT clobbered with zeros; dw1 reads real data and still MACs to zero. Wall = cold-start CMAC-arm, data-independent.)

The NPU-intermediate cache-coherency/clobber hypothesis (dirty CPU zero-lines on the producer-output ==
consumer-input BO get written back after the producer's NPU write, so the consumer reads zeros) is
DISPROVEN by the all-tasks readback already on disk — no new build/flash required:
- dw1's `in ` probe iova == conv0's `out` iova == `0xfeb2d000` (the SAME physical BO; producer output
  IS consumer input). It reads **distinct=242 (RUN3, chain) / 244 (RUN1, seq-kick), min=00 max=ff** — a
  full real feature map. The readback path is `dma_sync_for_cpu` (invalidate) → read DRAM, so 244 means
  **DRAM genuinely holds conv0's real output**; a zero-clobber would have made it read 0.
- Nothing writes `0xfeb2d000` between conv0 (task 0) and dw1 (task 1), so at dw1's read time it was 244.
  **dw1 reads dt_rd=20384 of REAL input and still writes all-zero (distinct=1).**
- A `dma_sync_for_device`-all-BOs flush would clean CPU→DRAM, but the input DRAM is already real — there
  is nothing to clean that changes dw1's read. The flush test is predicted to be a no-op and was NOT
  built (would cost a flash to confirm what the log already shows).

So the discriminating variable is NOT input content (it is real) — it is task POSITION / cold-start:
conv0 and a standalone dw (first/only task) compute; dw1 (a later task) reads the same real bytes and
does not MAC. **Wall = only the cold-start task after NPU-init arms the CMAC; data-independent.** Next
lever is Stage-2 (rknpu init path / what one-time state the first task consumes), NOT coherency.

## 2026-07-04 (★★ DIAGNOSTIC GAP CLOSED — the "empty MAC" verdict was a MEASUREMENT ARTIFACT. The all-tasks readback shows conv0 does a REAL MAC (distinct=242/244, full 0x00–0xff) in EVERY dispatch mode, including the task_number=N chain. conv0 is EXONERATED. The sole remaining wall: every layer AFTER conv0 reads its input but its CMAC never fires — only the cold-start/external-input layer computes.)

Board test of the all-tasks readback (kernel branch rk3576-readback-alltasks, fe66cfa59: the post-completion
readback now loops over ALL `j->task_count` tasks and labels each `out` line with the real task index, instead
of only dumping `next_task_idx-1` = the last, never-run task). Same 3-run harness (RUN1 baseline seq-kick /
RUN2 nextptr+task_number=1 / RUN3 nextptr+task_number=N).

- **conv0's MAC is REAL, everywhere.** task=0 output-BO distinct histogram across all runs: `239 ×1, 242 ×6,
  244 ×12` (min=00 max=ff = a full feature map). The only `distinct=1` task=0 lines (×6) are a *different*
  single-task tail job's task 0, not conv0. **conv0 computes a real map even in the task_number=N chain (RUN3:
  `task=0 0xfeb2d000 distinct=242`).** The earlier "conv0 commits (dt_wr=25088) but the MAC is empty
  (distinct=1)" was read off the WRONG BO (task 28, the never-run last task). **conv0 / requant / conv0 weight
  layout are all EXONERATED — that path is correct and done.**
- **No layer after conv0 ever does a real MAC.** In the task_number=N chain (RUN3) every task=1..28 is
  `distinct=1 min=00 max=00` (dw1 at 0xfea69000 reads its input — dt_rd=20384 — but writes all-zero). In RUN2
  (task_number=1) likewise nothing past conv0. The ONLY non-cold `distinct>1` lines are in RUN1 (seq-kick) and
  are FALSE signals: `task=2 distinct=2` = values {00,80} = DPU wrote the requant zero-point, MAC contributed
  nothing; `task=3 distinct=3` = bytes `7f 80 7f 7f 0d 80 7f 80` **byte-identical across 8 inferences** =
  stale/constant, not a fresh MAC. Nothing past conv0 produces a real feature map in any mode.
- **★ The wall, now confirmed on the RIGHT BO:** only the cold-start / external-input layer (conv0) does a real
  MAC; every chained layer reads its input yet its CMAC never fires. This is exactly the "only the COLD-START
  task does MACs" wall from the topic file — previously inferred, now DIRECTLY measured.
- **Direction change.** Stop investigating conv0/requant/weight-layout (correct + done). The entire remaining
  problem is the chained (non-cold) layer's CMAC. Prime suspect stands: dw1 reads conv0's real `0xfeb2d000`
  (known distinct=242) but outputs zero — either "only the first task the PC executes arms the CMAC", or an
  NPU-write→NPU-read visibility gap. In seq-kick, conv0/dw1 are separate jobs, so dw1's `in ` probe reads
  `0xfeb2d000` directly — NEXT: check whether dw1's `in ` shows the real 242 or 0/stale.

## 2026-07-04 (task_number=1 REFUTED — the RK3576 PC follows the trailer only at task_number=N, not =1 (opposite of RK3588). AND a diagnostic gap surfaced: the continuous-mode readback dumps the LAST task (28), never conv0, so the "empty MAC" premise is UNCONFIRMED — conv0's actual output in a chained submit has never been seen.)

Board test of `rocket.chain_task_number=1` (override PC_TASK_CON task_number field to 1 while the trailer stays;
kernel branch rk3576-chain-tn1, d168a289a). RUN 2 (task_number=1) vs RUN 3 (task_number=N contrast):
- **task_number=1 does NOT chain.** RUN 2: `TASK_CON=0x00010001` (field=1, override confirmed), but `top dt_rd`
  peaked at 9408 — only conv0's operands loaded, the PC ran ONE task and stopped, no trailer follow. RUN 3
  (field=N) reproduced dt_rd=29792 (conv0+dw1, one hop). **So the RK3576 PC follows the trailer only in
  task_number=N mode; at task_number=1 it runs a single task — the OPPOSITE of upstream RK3588 (task_number=1 +
  trailer chains).** The task's premise (port RK3588's task_number=1 + trailer) does not hold on RK3576. So
  trailer-follow (needs task_number=N) and single-task committing mode (task_number=1) are mutually exclusive
  here.
- **★ Diagnostic gap — the "empty MAC" premise is UNCONFIRMED.** The whole-graph readback dumps the BOs of task
  `next_task_idx-1` = 28 (the LAST task, which never runs) — e.g. RUN 2's only output readback is
  `out task=28 iova=0xfe250000 distinct=1`. **conv0's own output BO has NEVER been read back in a chained
  submit.** So the earlier "conv0 commits (dt_wr=25088) but the MAC is empty (distinct=1)" was inferred from the
  WRONG BO (task 28, or a mislabeled task=0 iova). conv0's real MAC quality in a task_number=N chain is unknown.
  If conv0 actually computes real there and merely fails to advance past dw1, the problem is ADVANCE, not MAC —
  a completely different shape. NEXT (must do before more levers): fix the readback to dump the FIRST task's
  (conv0's) output BO in continuous mode, and settle real-vs-empty definitively.

## 2026-07-04 (★ PARTIAL BREAKTHROUGH — the RK3576 PC DOES follow next-pointers. A task_number=N submit advanced past conv0 for the first time: the PC chained conv0→dw1 and loaded dw1's operands. This overturns the "iteration only / silicon wall" conclusion. The empty-MAC wall persists though, and the chain stalls after one hop.)

Board test of the next-pointer build (ROCKET_NEXTPTR trailer + wg_continuous task_number=29), RUN 2 vs the
baseline seq-kick RUN 1:
- **The PC followed the trailer.** RUN 2's first job: `top dt_rd=29792 wt_rd=132`. From the baseline, conv0 =
  dt_rd 9408 / wt_rd 96 and dw1 = dt_rd 20384 / wt_rd 36. **9408+20384 = 29792 and 96+36 = 132, exactly** — so
  the PC loaded conv0's operands AND dw1's operands in one submit. Before the trailer (Fork A EXP-1), the same
  task_number=N submit loaded only conv0 (dt_rd=9408). **So the RK3576 PC does follow next-pointers — the first
  time a multi-task submit ever advanced past conv0.** This contradicts the earlier "the PC only auto-strides,
  the wall is silicon" conclusion.
- **conv0 now commits.** core dt_wr went 0 → 25088 (before the trailer, task 0 of task_number=N never committed).
- **But two walls remain.** (1) The output is degenerate (distinct=1): conv0 wrote 25088 bytes but the MAC was
  empty (bias→relu→zp), the same task_number≥2 empty-MAC. (2) The chain stalled after one hop — dt_rd never
  exceeded 29792 (task 2 / pw1's 5152 never loaded), TASK_STATUS stuck 0/29; dw1 loaded its operands but never
  committed, so the PC stalled at dw1.

**This reopens everything.** The multi-task wall was never "the PC can't chain" — it CAN (conv0→dw1 proven).
The remaining wall is the empty MAC in task_number≥2 mode: even task 0 computes nothing when task_number=29,
though it commits and advances. The natural next lever falls straight out of it: run each task in the committing
(task_number=1) mode while the trailer does the advancing — i.e. dispatch task_number=1 + the next-pointer
trailer, so the PC follows the chain but each task runs in the mode that does real MACs. NEXT: task_number=1 +
trailer (a kernel knob to submit task_number=1 with the chained regcmd).

## 2026-07-04 (The next-pointer path is the ONE untried PC mechanism and is worth trying — correcting my earlier over-hasty dismissal. It is RK3588's tile-chaining, not a whole-graph or a vendor-RK3576 mechanism, so this is a NOVEL cross-op construction and a gamble on whether the RK3576 PC follows next-pointers — but it is a DIFFERENT PC code path than the walled iteration, and it could keep each task in the committing (task_number=1-like) mode while the trailer advances.)

Woo relayed a task to route RK3576 through RK3588's embedded next-pointer chaining. Read the code to judge it:
- **The trailer is two PC registers.** RK3588's `rkt_fill_regcmd` ends each task with `EMIT(REG_PC_BASE_ADDRESS,
  0)` + `EMIT(REG_PC_REGISTER_AMOUNTS, 0)` (rkt_regcmd.c:1283-1285); `compile_operation` patches them with the
  next task's address/count (`|= next_addr<<16`, rkt_ml.c:293-306), guarded `soc != RK3576`. REG_PC_BASE_ADDRESS
  = 0x10 = RK3576's PC_DATA_ADDR, so the trailer registers exist on RK3576 — mechanically portable.
- **But the next-pointer chains TILES within one operation** (compile_operation loops `operation->tasks`), not
  layers across the graph. On RK3588 the whole graph is **per-op jobs** (one DRM job per layer); cross-layer is
  DRAM. MobileNet's mostly-single-tile layers (num_tasks=1) emit NO trailer, so next-pointers are not even what
  makes RK3588's MobileNet work.
- **The vendor RK3576 works via task_number=N iteration with NO trailer.** So next-pointers are NOT "the missing
  RK3576 piece the vendor has" — the vendor doesn't use them. This corrects the task's framing.

**Corrected judgment (my earlier FINDINGS dismissal "next-pointer is not the RK3576 mechanism" was a
non-sequitur — the vendor choosing iteration doesn't preclude the RK3576 PC also following next-pointers).**
Worth trying, because: (1) our only tried multi-task path (task_number=N iteration) walls, byte-identical to the
vendor yet failing — an unresolved paradox; (2) the next-pointer is a DIFFERENT PC code path the audit never
touched; (3) if the whole graph is chained task-by-task via trailers with each task run in the committing
(task_number=1-like) mode and the PC advancing on the trailer, it could sidestep the task_number≥2 commit gate
entirely. Honest unknown: the vendor doesn't use next-pointers on RK3576, so whether the RK3576 PC follows them
is the experiment — if it does, later tasks compute (dt_wr>0, distinct>1); if not, the chain stops after task 0.
Implementation is NOT a direct RK3588 port (that's per-op tile chaining) but a novel cross-op construction: emit
the trailer in the RK3576 fills + patch next-pointers across the whole packed graph + dispatch so the PC walks
the chain. Cheap (build; Woo flashes), resolves the question either way. Branches rk3576-nextpointer (mesa+kernel).

## 2026-07-04 (Audit COMPLETE — the completion path, perf counters, and clock/power/iommu are clean too. Every software path is byte-identical/equivalent to the vendor. No software bug anywhere in the audited surface; the multi-task wall is definitively the PC's internal task_number≥2 behavior.)

Finished the audit — the completion/finalize path and the environment:
- **Completion + finalize are correct.** poll_timer_fn (multitask) waits PC_TASK_STATUS==task_count with a
  500ms cap, then schedule_work → handle_irq → finalize; finalize re-kicks while next_task_idx < task_count and
  signals the fence + puts pm_runtime when all tasks are consumed (rocket_job.c:2136-2144). Correct.
- **Perf-counter offsets are correct.** Vendor rknpu_top_amount = 0x2210/0x2234/0x2238/0x223c and
  rknpu_core_amount = 0x2410/0x2434/0x2438/0x243c; ours read 0x210/0x234/… (top) and 0x410/0x434/… (core) from
  stats_iomem, i.e. our stats_iomem base is the vendor's core+0x2000 — the offsets match. And single-task reads
  dt_wr=25088 correctly, so **dt_wr=0 in multi-task is a REAL zero, not a mis-read** (corroborated by output
  distinct=1).
- **Clock/power/iommu are not task_number-specific.** Single-task commits in the exact same environment (same
  clocks/PVTPLL, same power domain, same attached domain), so none of these can gate a task_number≥2-only
  failure.

**AUDIT CONCLUSION (thorough).** Everything the software controls is byte-identical or equivalent to the vendor
across every path: the packed regcmd bytes (part 2), the submit register sequence (part 1), the requant, the
S_POINTER, the completion, the perf offsets, state_init/arm/pulse, and no 0xf008 either side. There is **no
software bug in the audited surface.** The multi-task wall — task_number≥2: task 0 loads its operands (dt_rd>0)
but the CACC never commits (dt_wr=0, output distinct=1) and PC_DONE asserts instantly (samples=1), while
task_number=1 with the identical stream commits (dt_wr=25088) — is the **PC task-sequencer's internal behavior
for task_number≥2**, below the software surface. That is the definitive, audited answer to a month of walls.

## 2026-07-04 (Audit part 2 — the per-layer regcmd is CLEAN too: requant/OUT_CVT is validated and the model is per-tensor; the S_POINTER value matches the vendor and the mesa comment's own "0x0e desyncs multi-task" theory is REFUTED by the vendor using 0x0e as well.)

Continued the audit into the mesa per-layer regcmd generation (rkt_regcmd.c fill_regcmd_rk3576_normal):
- **Requant / OUT_CVT is validated.** `conv_scale = in_scale*wt_scale/out_scale → cvt_scale (15-bit) + shift`
  (rkt_regcmd.c:352-360). This is the same math proven byte-exact on conv2d-cal, and mobilenet_v1_1.0_224_quant
  is per-tensor (single weights_scale), so a scalar requant is correct. offset = output_zp - 0x80. Not a bug.
- **S_POINTER value matches the vendor.** mesa's default per-task `sptr = 0x0e` (ROCKET_SPTR, rkt_regcmd.c:400):
  POINTER=0 | PP_EN | EXECUTER_PP_EN | PP_MODE(1). The mesa comment (380-397) theorises that PP_MODE=1
  auto-alternates the ping-pong group and DESYNCS on a multi-task graph → geometry lands in a group the executer
  never reads → "units engage but the DPU writes nothing" (= the dt_wr=0 symptom). BUT the vendor's own dw
  regcmd entry[0] is `reg=1004 val=0x0e` — the vendor uses the SAME 0x0e (PP_MODE=1) and its multi-task works.
  So the desync theory is REFUTED and 0x0e is not the bug.

So both the submit path (part 1) and the per-layer regcmd (part 2) are clean and vendor-matching. Everything the
software controls — the packed bytes and the submit register sequence — is byte-identical to the vendor across
every path audited. The remaining anomaly (vendor's bare pulse engages, ours needs the per-unit op_ens; and
task 0 never commits in task_number≥2 with a byte-identical stream) has no software cause left in the audited
surface. Still unaudited: the completion/finalize path and the clock/power/iommu environment (both unlikely to
gate a task_number-specific commit, since single-task commits in the same environment).

## 2026-07-04 (Audit part 1 — the kernel submit path + mesa whole-graph packing are CLEAN: they match the vendor. No second bug there. Reinforces that the multi-task wall is the PC's internal task_number≥2 behavior, not a submit bug. Still to audit: completion path, per-layer regcmd correctness, clock/power/iommu.)

Chewed through the kernel `rocket_job_hw_submit` and mesa `rkt_pack_graph_regcmd` line by line vs the vendor
`rknpu_job_subcore_commit_pc`:
- **The commit_pc 8-step sequence matches** (S_POINTER arm 0xe on CNA 0x1004 / CORE 0x3004 → PC_DATA_ADDR
  (0x10) → PC_DATA_AMOUNT → INT_MASK=last → INT_CLEAR=first → PC_TASK_CONTROL (0x30) → PC_DMA_BASE_ADDR →
  PC_OP_EN 1→0). Order and values match; RKNPU_OFFSET_PC_DATA_ADDR=0x10 == our BASE_ADDRESS.
- **`BASE_ADDRESS=0x1` (rocket_job.c:893) is harmless dead cruft** — PC_BASE_ADDRESS bit0 is PC_SEL (TRM-reserved);
  it's overwritten by the regcmd-addr write at :972, and the vendor also leaves PC_SEL=0 (regcmd_addr is aligned).
- **The vendor NEVER writes 0xf008 (ENABLE_MASK) anywhere** (only the macro + a struct field exist); its units
  engage from rk3576_state_init + the per-submit S_POINTER arm + the PC_OP_EN pulse — identical to ours.
- **rk3576_state_init == our rocket_core_pp_state_init** exactly (re-confirmed).
- **The whole-graph stride is NOT a bug.** mesa packs at a uniform `stride_amount = ((max_amount+5)/2)*2`
  (rkt_ml.c:140) and reports every task's amount as that uniform stride (all 522 kicks show DATA_AMOUNT=0x49 =
  143), so the kernel's PC_DATA_AMOUNT (from task[0]) equals the packing stride — the PC strides correctly and
  shorter tasks are zero-padded to the stride.

So the submit path is clean and vendor-matching. The one thing that still doesn't add up structurally: the
vendor's single PC_OP_EN pulse engages its units (no in-stream op_en, no 0xf008) while ours needs mesa's
injected per-unit op_ens to engage — with a byte-identical arm+pulse+state_init. That per-unit-op_en engage is
what loads the operands in continuous mode (dt_rd=9408) but the CACC still never commits (dt_wr=0). NOT YET
AUDITED (bugs may hide here): the completion/finalize path, the per-layer regcmd generation in mesa
(requant/OUT_CVT, feature/weight/bias addresses, DPU+RDMA config — correctness bugs that would bite the chain
once it runs), and the clock/power/iommu environment.

## 2026-07-04 (Reframe: the next-pointer angle is not the RK3576 mechanism [vendor uses pure task_number iteration, which WORKS for the vendor], so the wall is not the bytes or the mechanism — it is OUR rocket driver's task_number=N execution environment. Even the vendor's exact bytes replayed through our driver wall in ONEJOB mode. Next: a thorough audit of the driver's whole submit→completion path.)

Checked the RK3588 self-chain next-pointer path (rkt_ml.c:282, guarded soc!=RK3576) as the last "adapt working
code" lever. The vendor RK3576 dw regcmd (vendor_dw_regcmd.txt) ends in real unit registers (RDMA 0x507c) with
NO PC/next-pointer entries — so RK3576 uses pure **task_number iteration** (the PC auto-strides the packed
regcmd array), not RK3588's embedded next-pointers. And **the vendor's iteration WORKS** (its whole graph
computes). So the mechanism isn't broken and next-pointers aren't the RK3576 path.

That reframes the wall precisely: **the vendor's task_number=N iteration works; ours walls — with byte-identical
regcmd AND byte-identical submit registers. And the vendor's own captured bytes, replayed through our rocket
driver, ALSO wall in ONEJOB (task_number=N) mode while SPREAD (N jobs) computes conv0.** So the wall is not in
mesa and not in the command stream — it is in **our rocket driver's task_number=N execution environment** (the
clocks/PVTPLL, genpd power, rk_iommu, soft-reset, PC write ordering — everything the driver sets up around the
byte-identical submit). Precedent: the VoidChecksum RK3576 rocket series needed extra kernel fixes (SError /
IOMMU / CBUF-zero, forks 0002/0005/0009/0010) just to run on real HW, so the multi-task wall is plausibly
another driver-environment hole, not microcode. NEXT: audit the driver's whole submit→completion path against
the vendor rknpu_job_subcore_commit_pc, looking for MORE than one gap (clock/power/reset/iommu/PC-ordering).

## 2026-07-04 (The IRQ-completion lever is DEAD on inspection — the wall is now pinned to one screw: in task_number≥2 mode the PC asserts PC_DONE instantly [samples=1] without ever driving the DPU [dt_wr=0], while task_number=1 drives it [dt_wr=25088]. Pure internal PC-sequencer behavior; no driver lever reaches it.)

Inspected the IRQ-completion lever (the one Fork A path never tried) before building it — and it is already
effectively present and does not touch the gate:
- **The IRQ path is already wired.** `rocket_job_irq_handler` (rocket_job.c:2222) already fires on
  INTERRUPT_RAW_STATUS bits 0-13 (which include 0x300 = the DPU-done bits), clears them, and wakes the thread →
  the same completion handler the poll uses. So "switch to IRQ completion" changes nothing structural.
- **int_mask already == the vendor's 0x300** (confirmed from the capture). No difference.
- **The PC advances tasks internally.** The vendor enables only the LAST task's int_mask and waits for that one
  IRQ; it does not service per-task interrupts. So the task-to-task advance is the PC's own hardware, not
  driver-serviced — poll-vs-IRQ cannot change it.
- **The "in-execution polling perturbs the DPU" confound is also dead.** In continuous mode the cnalive sample
  loop showed `samples=1` — it broke after ONE read because PC_DONE was already set. So there was no heavy
  in-execution polling to perturb anything.

That last point exposes the wall's true shape: **in task_number≥2 mode the PC asserts PC_DONE immediately
(samples=1) and task 0's DPU never writes (dt_wr=0); in task_number=1 mode the PC drives the DPU to completion
(dt_wr=25088).** The only register that differs between the two is the task_number field of PC_TASK_CONTROL
(1 vs N) — everything else (int_mask, op_en, S_POINTER arm, state_init, the whole regcmd) is byte-identical to
the vendor. So the gate is the **PC task-sequencer's internal behavior for task_number≥2**, below the register
surface, unreachable from the driver.

**Software levers exhausted.** Ruled out, each with board or offline evidence: dispatch model (sequential kicks
vs continuous vs SPREAD), per-kick teardown (bisect 0xf), resume soft-reset, reset-per-layer (crashes), regcmd
bytes (byte-identical to the vendor), input data + coherency (dw1 reads conv0's real output), pw/dw/weight-fetch
(red herrings), op_en value, ENABLE_MASK-at-submit, cache_sgt/NBUF (vendor chains via DRAM), IRQ completion.
The wall is RK3576-specific PC microcode; RK3588's open stack works because it self-chains via embedded
next-pointers (rkt_ml.c:282, guarded soc!=RK3576) — the untried RK3576 analogue.

## 2026-07-04 (Lead A [cache_sgt/NBUF] is a DEAD END — verified: the vendor chains layers through a 2 MB DRAM intermediate, not NBUF. So the sole mechanism that makes chained layers compute is the continuous PC submit, which walls for us. Next: the one untried Fork A lever — IRQ-driven completion + per-task int_mask instead of PC_DONE polling.)

Before building the (large) cache_sgt machinery, checked whether the vendor actually puts intermediates on-chip.
The vendor MobileNet capture (dirty/rknpu_replay/meta.txt): `bo idx=2 dma=0xffde1000 size=2158592` — the
intermediate activation buffer is **2.06 MB, DRAM-backed** (a normal 0xffde1000 IOVA), which cannot fit in the
1 MB NBUF; no BO in the capture is NBUF/cache-backed. So **the vendor chains layers through DRAM exactly as we
do; cache_sgt/NBUF is orthogonal to the chained-layer-MAC wall.** Lead A is dead. The vendor's chained layers
compute purely because of the **continuous PC submit** (one job, task_number=24, the PC managing the CBUF
pipeline task-to-task) — the operand location (DRAM) is identical to ours. And the continuous submit is exactly
what walls for us (Fork A: task_number≥2 → task 0's CACC never commits, PC wedges). So **"chained layers don't
MAC" and "continuous submit walls" are one wall: the PC-managed CBUF pipeline of the continuous submit.**

The one Fork A lever never tried: the vendor completes by **interrupt** — it enables the per-task int_mask
(0x300 = the DPU-done bits) in INTERRUPT_MASK and waits on int_status; our driver polls PC_DONE (bits 28/29,
which are read-only in INTERRUPT_MASK on RK3576) with an hrtimer and never services a per-task IRQ. If the PC's
task-to-task advance is gated on the per-task DPU-done interrupt being raised/serviced, then polling PC_DONE
without servicing that interrupt would stall the PC after task 0 — which is exactly the wedge we see. NEXT:
implement the vendor's IRQ-driven completion (per-task int_mask, service the NPU IRQ, advance on int_status) and
re-test the continuous submit.

## 2026-07-04 (Fork B — the resume soft-reset is NOT the MAC-enabler [REFUTED], the reset-per-layer fix CRASHES, and a self-check debunks the "bytes-vs-context" pivot: the "vendor dw computes" evidence was an EXTERNAL-INPUT dw, not a chained layer. No chained/later layer has ever computed on this open stack, in any dispatch mode.)

Two board runs + one offline self-check, all pointing the same way:

**(1) The resume soft-reset hypothesis, REFUTED.** The runtime_resume callback runs a full NPU soft-reset
(rocket_core_reset) and its comment claims "without the CBUF reset ... the CMAC reads zero out of an
uninitialised CBUF." So I guessed the cold-start's reset is what enables its MACs. Board control
`rocket.soft_reset=0` (verified it took effect — log shows "soft_reset=0, skipping full NPU reset" on a real
resume): **conv0 still computes (distinct=241).** So the resume soft-reset is NOT the MAC-enabler; conv0 does
not need it. Hypothesis dead.

**(2) The reset-per-layer fix, CRASHES.** `rocket.rekick_reset=2` (detach IOMMU → rocket_core_reset →
re-attach, per re-kick) faulted: `rocket_gem_bo_free → iommu_unmap` NULL deref at cleanup, "recursive fault,
reboot needed" — my inline detach/re-attach corrupts the domain's iommu mapping state, so freeing BOs later
NULLs. A driver bug in the experiment, not a HW verdict; dw1 stayed distinct=1 anyway. (The mid-graph
detach/reset/re-attach domain is exactly what the prior cbuf_reset=2 / power-cycle attempts died in.)

**(3) Self-check — the "bytes-vs-context" pivot is SHAKY.** I'd concluded "it's context, not the regcmd bytes,
because the vendor's dw computes from byte-identical bytes." Re-reading how that was measured (replay_rocket.c
SPREAD = N single-task DRM jobs in one submit ioctl, one session): the "standalone dw112 computes" case is a
dw reading **external** DRAM input — it computes for the same reason conv0 does. The **chained** SPREAD replay
(conv0→dw1→pw1→dw2) showed conv0 compute and **every chained layer read nothing (dt_rd=0) and produced
nothing.** So there is NO evidence any chained/later layer has ever computed on this open stack, vendor bytes or
ours, in any dispatch mode. The honest statement: **the first/external-input layer always computes; a
chained/later layer never has.** The byte-diff (mesa dw regcmd == vendor dw regcmd) is still a fact; what's not
supported is the leap "therefore a comparable computing case exists, so it must be context."

**What this sharpens.** Our mesa sequential-kick dw1 is actually one step further than the SPREAD chain: warm-
chain makes it **read its input** (dt_rd=20384, from conv0's real output feb2d000 which holds distinct=239),
yet it still does no MAC. The only difference between the computing standalone-dw and the non-computing
chained-dw1 is external-input vs intermediate-input. **Prime suspect: does dw1's CNA actually read conv0's REAL
output, or stale/zero data?** dt_rd=20384 says it read 20384 bytes, not that the bytes were right — an
NPU-write-then-NPU-read producer/consumer coherency gap would give a warm-looking read of zeros → MAC on empty
→ degenerate. NEXT: before dw1's submit, dump the actual bytes of its input BO (feb2d000) — conv0's distinct=239
real data, or zeros? Real data → it genuinely is "later layers don't MAC" (HW state); zeros → a coherency bug,
tractable.

**Coherency REFUTED (from the existing log, no board cycle).** The driver's own input readback already answers
it: `buf[3] in task=1 iova=0xfeb2d000 first=b8 7f 33 e5 80 7f 3d 7f ... distinct=237` — dw1's input BO holds
conv0's REAL output (distinct 237/241/240, matching conv0's output), correctly aliased (dw1-in iova == conv0-out
iova == feb2d000). The driver reads real data from feb2d000 between the kicks; dw1's CNA reads the same physical
via the same IOMMU — so dw1 reads its real input and still does no MAC. Not stale, not zero. So the wall is now
as tight as software can make it: a layer reading EXTERNAL (CPU-provided) input computes; a layer reading an
INTERMEDIATE (NPU-produced, real, correctly-addressed, byte-identical regcmd) input does not, in every dispatch
mode. Ruled out: regcmd bytes, teardown, resume soft-reset, input data, coherency, dispatch mode. The one thing
left that differs between conv0 and dw1 is the on-chip CBUF/CMAC STATE conv0 leaves behind (independent of dw1's
DRAM input), which no software lever re-initialises without cooling the CBUF (warm-chain) or crashing (reset).
→ lead (A): the vendor's on-chip-buffer mechanism (cache_sgt/NBUF) + the PC-managed CBUF pipeline of the
continuous submit.

## 2026-07-04 (Fork B teardown bisect — the per-kick teardown is EXONERATED. Skipping ALL of it does not restore a re-kick's MACs. The MAC-enabler is the fresh-job context, not any between-kick software step.)

Added `rocket.bisect` (bitmask) to disable each per-kick teardown step and measured the true dw1 output
(iova 0xfea69000; the task-index labels in the buf readback are unreliable — a readback of conv0's bo was
mislabeled task=1 d=238, which is NOT dw1). One boot, sequential-kick mode, sweeping bisect:

| bisect | disables | conv0 (feb2d000) | dw1 (fea69000) |
|--------|----------|------------------|----------------|
| 0 baseline | — | 235 | **1** |
| 0xf | ALL teardown | 238 | **1** |
| 0x1 | sptr-toggle diag | **98** (worse) | 1 |
| 0x2 | sptr-rearm | 239 | 1 |
| 0x4 | int-clear-full | 238 | 1 |
| 0x8 | perf-clear | 236 | 1 |

**dw1 stays distinct=1 in every configuration, including 0xf (skip ALL teardown).** So none of the between-kick
software steps — the diagnostic S_POINTER 0→1 toggle, the driver S_POINTER re-arm, the full INTERRUPT_CLEAR, the
perf-counter clear — is the MAC-killer. **The per-kick teardown is exonerated; the original instinct is wrong.**
(Side note: skipping the diagnostic S_POINTER toggle, 0x1, made conv0 *worse* — 235→98 — so that toggle is
somehow helping the group state, not hurting it.)

So the discriminator is the **fresh-job context vs a re-kick**, not any register we clear between kicks:
- the vendor's standalone dw112 replayed as 6 separate single-task **jobs** computes;
- our dw1 as a **re-kick within one job** does not — same input read (dt_rd=20384), byte-identical regcmd.

The only thing a job boundary does that a re-kick doesn't: `pm_runtime_get_sync` + drm_sched arbitration +
`dma_fence_signal` + `pm_runtime_put_autosuspend`. The leading hypothesis is that **`pm_runtime_get_sync` (the
per-job PM resume) re-inits some HW state that enables the MACs, and a re-kick — which skips it — runs on a
state the first task consumed.** NEXT: dispatch each layer as its own DRM job (fresh pm_runtime_get_sync per
layer) with the intermediates persisted in DRAM, and see whether dw1 then computes (distinct>10). If yes, the
fix is per-job dispatch (not re-kicks); if no, even a fresh job doesn't help and the enabler is narrower
(a genuine per-inference/reset state).

## 2026-07-04 (Fork B byte-diff — the mesa dw regcmd is byte-identical to the vendor's; the bytes are NOT why it produces zero. It is EXECUTION CONTEXT. Next: bisect the per-kick teardown.)

To settle bytes-vs-context: byte-diffed the live mesa dw1 regcmd (board dump_regcmd, 139 entries) against the
vendor's captured dw regcmd (vendor_dw_regcmd.txt run 0), register by register, all four targets:

| target | identical | differs |
|--------|-----------|---------|
| CNA (0201) | 42/44 | 0x1088 (feature addr), 0x1110 (weight addr) — absolute IOVA vs vendor offset, both functional |
| CORE (0801) | 5/5 | — |
| DPU (1001) | 64/68 | 0x4018 (output addr — addressing); 0x40ac/0x40b0/0x40b4 (requant offset/mul/shift) |
| RDMA (2001) | 19/21 | 0x5020, 0x5024 (bias addr — addressing) |

The ONLY non-address value differences are the DPU requant triplet 0x40ac/0x40b0/0x40b4. Effective scale:
mesa 0x4ace>>0x10 ≈ 0.29 vs vendor 0x60e9>>0x18 ≈ 0.0015 — a ~200× gap, so the vendor capture's dw is a
DIFFERENT layer/model (same shape, different quant scales), not a mesa bug. (An earlier pass wrongly reported
mesa "omits the DPU_RDMA" — that was a log-extraction truncation: the dw dump runs lines 1166–1440 and the RDMA
tail 0x500c–0x507c sits at 1420–1440; mesa DOES emit the full DPU_RDMA incl. bias 0x5020/0x5024.)

So: **the mesa dw regcmd is byte-identical to the vendor's (modulo addresses and a different-layer requant).
The regcmd bytes are NOT why mesa's dw produces zero** — and yet mesa's dw1 *reads its input* (dt_rd=20384),
has a correct regcmd, and still outputs distinct=1. **The MAC-suppression is EXECUTION CONTEXT, not the command
stream.** This validates the original instinct: the cold-start task 0 runs on fresh HW state and does MACs; task
1 runs on the state task 0 left — correct regcmd, input read — and the CMAC never fires. NEXT: bisect the
per-kick teardown (OP_EN 1→0 vs leave high; skip the S_POINTER re-arm; skip INT_CLEAR; skip the perf-counter
clear) to find which step, removed, lets task 1 compute (distinct>10) — that isolates the state the cold start
consumes and later tasks lack.

## 2026-07-04 (Fork B — THE UNIFICATION: only the cold-start task does MACs. Every subsequent task, whether a sequential re-kick or a multi-task PC iteration, engages and loads its operands but does NO MACs. dw/pw/weight-fetch are red herrings.)

Picked B (make the sequential model correct) and mapped the per-task output of the working sequential-kick run
(RUN 1, MobileNet whole-graph, 29 tasks). The output `distinct` (a proxy for "did it compute") is decisive:

| task | layer | 0x100c mode | exec_ever | wt_rd (top) | out distinct |
|------|-------|-------------|-----------|-------------|--------------|
| 0 | conv0 (COLD start) | 0x2000a006 firstconv | 0xf | 96 | **239 (computes)** |
| 1 | dw1 | 0x1 dw-mode | 0xf | 36 | 1 (degenerate) |
| 2 | pw1 | 0x0 standard | 0x0 | 0 | 2 |
| 3 | dw2 | 0x1 dw-mode | 0xf | 128 | 3 |
| 4 | pw2 | 0x0 standard | 0x0 | 0 | 4 |
| 5 | dw3 | 0x1 dw-mode | 0xf | 72 | 2 |
| 6.. | rest | | | 0 | 1 (chain goes quiet) |

**Only task 0 (the cold-start conv0) actually does MACs (distinct=239). Every task after it — depthwise AND
pointwise alike — produces a degenerate output (distinct 1–4), no matter that the dw's engage (exec_ever=0xf)
and fetch weights (wt_rd=36/128/72).** So the whole "pointwise doesn't fetch weights / standard-mode doesn't
engage" line is a **red herring**: the dw fetches weights and engages and STILL produces nothing; the pw's
exec_ever=0 and wt_rd=0 don't matter because even a fully-engaged weight-fetching dw computes nothing. **The
real split is cold-start vs everything-after, not dw vs pw.**

This UNIFIES the two walls into one:
- **Sequential model**: only the first kick (cold-start conv0) does MACs; every re-kick after it is degenerate.
- **Continuous model**: task 0 is the cold start yet its CACC never commits (dt_wr=0) — the multi-task commit
  gate sits ON TOP, so not even the cold start computes there.
- **Same root** (= the git-HEAD "single-task-vs-multi-task line is the whole remaining mystery"): the CMAC only
  fires on the FIRST task of a fresh HW context. Some state the cold start runs on is consumed/spoiled and not
  restored for later tasks. Our sequential kicks tear down between tasks (OP_EN 1→0 + S_POINTER re-arm +
  INT_CLEAR + perf-counter clear, even with warm-chain skipping pp_state_init); the vendor's continuous PC
  submit has NO teardown between tasks, so every layer runs in one warm context and computes. warm-chain earlier
  got the later layers to engage + DMA but NOT to do MACs — this is exactly why.

So B has no cheap pw-config win; B and A converge on one question: **how to make a non-cold-start task do MACs.**
NEXT (this session): find precisely which per-kick teardown step kills the MACs — bisect the between-kick
sequence (OP_EN 1→0 vs leave high; S_POINTER re-arm vs leave; INT_CLEAR; perf clear) to see which one, when
removed, lets task 1 compute (distinct>10). That isolates the state the cold start consumes.

## 2026-07-04 (Fork A experiment 2: op_en-value fork CLOSED; the multi-task submit is byte-identical to the vendor's, so the wall is not in the registers — the RK3576-specific piece rocket lacks is cache_sgt/NBUF-backed operands.)

Read the vendor rknpu driver end-to-end to find what a task_number=N submit does that we don't:
- **Vendor `rknpu_job_subcore_commit_pc` (rknpu_job.c:685-715): NO ENABLE_MASK (0xf008) write, NO in-stream
  op_en at all.** Just PC_DATA_ADDR, PC_DATA_AMOUNT, INT_MASK=last_task->int_mask, INT_CLEAR=first_task->
  int_mask, PC_TASK_CONTROL=((0x6|pp)<<16)|task_number, PC_DMA_BASE_ADDR, then one PC_OP_EN 1→0 pulse. Units
  engage from the per-submit S_POINTER arm (0x1004=0xe, 0x3004=0xe; rknpu_job.c:489-490) + the pulse.
- **The vendor capture (dirty/vendor.txt:1843) is byte-identical to ours**: `int_mask=0x300 first_int_mask=0x300
  task_con=0x70002 task_base_addr=0x0 pc_data_amount=71`. So our fixed INT_MASK=0x300 already matches (per-task
  int_mask ruled out), and the vendor's own multi-task submit is task_number=2 with the exact registers we write.
  **The multi-task wall is NOT in the submit register values.**
- **`rk3576_state_init` == our `rocket_core_pp_state_init` exactly** (BASE=0x1, S_POINTER 0→1→0x1e, DATA_SIZE1=
  0x80000000 into both groups). Ruled out.
- **`pc_dma_ctrl=1` (RK3576) just wraps the PC_DATA_ADDR write in irq_lock** — the register write is identical.
  No functional difference. Ruled out.
- **The ONE RK3576-specific mechanism rocket entirely lacks = `cache_sgt` (rknpu_gem.c:422
  rknpu_iommu_map_with_cache_sgt).** A BO allocated "with_cache" gets its OWN iova mapped to the on-chip NBUF
  SRAM physical (`nbuf_start=0x3fe80000`, 1 MB, in 448+64 KB blocks per core from `rk3576_cache_sgt_init`).
  This is the vendor's on-chip-buffer path — a per-BO alloc flag with a proper block layout, NOT the arbitrary
  driver remap Fork B tried (and it's why Fork B's iommu_map(0xfff00000) conflicted). mesa never allocates
  cache BOs, so our whole graph runs from DRAM.

op_en-value fork, board (wg_continuous=1, 3 runs): RUN 2 `ROCKET_UNIT_OPEN=0x1d` (per-unit op_en to CNA 0x1008/
CORE 0x3008/DPU 0x4008/RDMA 0x5008 with the FULL enable the broadcast uses, no PC 0x08 touch) and RUN 3
`=0x1` are **IDENTICAL**: conv0 top dt_rd=9408 wt_rd=96 (loads), core **dt_wr=0** (no commit), TASK_STATUS stuck
1/29. **So completion in task_number≥2 is NOT gated by the op_en value — the op_en engages the CNA DMA either
way, and the CACC never commits regardless.** Fork CLOSED: no op_en value/presence/target lever moves the
multi-task completion (broadcast wedges the PC, per-unit 0x1 and 0x1d both stall at 1/29, STRIP gives no DMA).
The completion gate is task_number≥2-intrinsic and carried by no register the stream writes.

**Two leads remain.** (A) **cache_sgt/NBUF on-chip operands** — the biggest untested RK3576-specific difference;
the multi-task PC pipeline may require on-chip (not DRAM) operands, which would also explain the original CBUF-
continuity / pw-weight-staging problem. Big: needs a cache-BO UABI + mesa allocating cache BOs + kernel
cache_sgt map. (B) **Abandon continuous submit as a wall** and pre-stage pw weights within the WORKING
sequential-kick model by a different route (the sequential model already carries engage + feature + dw weights;
only large pw weights need the pipeline). Decide direction before more board cycles.

## 2026-07-04 (Fork A experiment 1: engage × dispatch matrix) — the crux refined one layer: in task_number=N mode conv0 LOADS its operands byte-identically to the working single-task, but the CACC never commits (dt_wr=0) and the PC wedges. Engage and continuous-iteration are mutually exclusive in our mechanism.

Added `rocket.wg_continuous` (rocket_job.c): dispatch the whole job as ONE task_number=task_count PC submit
(vendor commit_pc), instead of N sequential single-task kicks. One board boot, three inferences differing only
in dispatch × op_en (all MobileNet whole-graph, task_count=29):

| RUN | dispatch | in-stream op_en | conv0 load (top) | conv0 commit (core dt_wr) | PC state |
|-----|----------|-----------------|------------------|---------------------------|----------|
| 1 | N sequential kicks | kept | dt_rd=9408 wt_rd=96 | **25088** | completes, output distinct=239 |
| 2 | continuous N=29 | kept | dt_rd=9408 wt_rd=96 | **0** | OP_EN stuck 1, PC_RAW bit16, TASK_STATUS never advances |
| 3 | continuous N=29 | STRIP_OPEN | dt_rd=**0** | 0 | units never engage, no DMA at all |

What this nails:
- **RUN 2 conv0 loads its input (dt_rd=9408) and weights (wt_rd=96) — the SAME counters as the working
  single-task RUN 1.** So the multi-task wall is NOT an operand/DMA-fetch problem; the operands are in.
- **Yet core/CACC dt_wr=0** (RUN 1 = 25088): the compute/write-back never commits. Same operands, same config;
  task_number=1 writes 25088, task_number≥2 writes nothing. This refines the old "engages but never completes
  its DPU write" — the DMA does run, only the CACC commit / done-handshake is gated.
- **The PC wedges**: OP_EN stuck at 1 + PC_RAW bit16 set. This is exactly the kernel-comment warning that the
  in-stream 0x1d op_en, firing mid-iteration, restarts/wedges the PC. (After the stall, mesa's later jobs come
  in with DATA_ADDR=0 and each stalls the 500ms cap — noise; the board recovered, RUN 3 ran clean.)
- **RUN 3 reverse-proof**: strip the in-stream op_en and conv0 does not even DMA (dt_rd=0). So the in-stream
  0x1d is what TRIGGERS the CNA feature/weight DMA in our path. It is required for engage AND it wedges the PC
  in multi-task mode.

So the dilemma is proven both ways: **engage (CNA-DMA trigger) needs the in-stream 0x1d op_en; continuous PC
iteration needs it absent (else the PC wedges, OP_EN stuck 1).** Mutually exclusive in our current mechanism.
The vendor decouples them by folding ENABLE_MASK (0xf008=0x1d) into the submit (no in-stream op_en at all), but
our CPU write of 0xf008=0x1d before OP_EN hangs (prior finding). **Next Fork A lever: replicate the vendor's
ENABLE_MASK-at-submit so the CNA engages without an in-stream op_en and without hanging — read the exact
ENABLE_MASK write/ordering in rknpu_job_subcore_commit_pc and find what our earlier hanging write was missing.**
(Correction to the prior entry's claim that STRIP_OPEN units engage from the S_POINTER arm + one pulse — RUN 3
disproves it for our 0x1 pulse: armed S_POINTER=0x0e + one pulse with no op_en → exec_ever=0, dt_rd=0.)

## 2026-07-04 (Fork A opened) — the vendor's rknpu driver gives the exact continuous-submit recipe; the "1/29 stuck" crux is now precise: a task completes as task_number=1 but not as task 0 of a task_number=N submit.

Read the vendor rknpu kernel driver (rk3576-vendor-kernel/drivers/rknpu) instead of guessing at NVDLA RTL —
the PC iteration is Rockchip's, not NVDLA's, so the vendor driver is the real reference. `rknpu_job_subcore_
commit_pc` writes, in order: PC_DATA_ADDR = first_task->regcmd_addr; PC_DATA_AMOUNT = (first amount + EXTRA +
scale-1)/scale-1; **INT_MASK = last_task->int_mask; INT_CLEAR = first_task->int_mask**; PC_TASK_CONTROL =
((0x6 | task_pp_en) << 16) | task_number; PC_DMA_BASE_ADDR = task_base_addr (0 in the capture); then a single
PC_OP_EN 1→0 pulse. Completion is by **interrupt** (wait_event on job->int_status, only the last task's int_mask
enabled), not our raw-PC_DONE poll.

Three facts fall out:
- **The RK3576 config matches ours exactly** (pc_task_number_bits=16, pc_task_status_offset=0x48,
  pc_data_amount_scale=2, max_submit_number=(1<<16)-1=65535). 65535 ≫ 29 tasks, so the vendor runs the whole
  graph in ONE submit — not small chunks. Config is not the difference.
- **The vendor's per-task regcmd has NO in-stream broadcast OP_EN.** Its targets are only 0x201/0x801/0x1001/
  0x2001 (CNA/CORE/DPU/RDMA) — never the 0x81 broadcast. So Mesa's per-task 0x81 op_en (value 0x1d) is a Mesa
  invention, and stripping it (ROCKET_STRIP_OPEN) is what matches the vendor. The units are meant to engage from
  the per-task S_POINTER arming (0x1004=0xe, which each task's regcmd carries) plus the one PC_OP_EN pulse — no
  per-task op_en at all.
- So with the vendor-matching stream (no in-stream op_en, one pulse, task_number=N), the units DO engage but
  task 0 never completes its DPU write (output distinct=1, PC_TASK_STATUS stuck at 0) — the PC waits for a
  completion that never comes and never advances. **Yet the identical task 0 completes fine as a task_number=1
  kick** (distinct=239). So the crux is exact and small: something about task_number≥2 mode gates task 0's
  compute completion (the DPU write / the done handshake the PC advances on). That is register/microcode-level.

Fork A campaign from here: find why a task completes as task_number=1 but stalls as task 0 of task_number=N —
by capturing the live unit/PC status of task 0 in each mode side by side, and matching the vendor commit_pc bit
for bit (per-task INT_MASK via a new UABI field, interrupt-driven completion, task_pp_en). The vendor driver is
the map; the seam is the multi-task completion handshake. (Kernel diagnostics for it: the arm/exec dumps
already in rocket_job.c; the vendor recipe above.)

## 2026-07-04 — where it stands: the whole chain runs except one piece, the pointwise weight pre-staging. Cheap paths (C: bank capacity, B: on-chip preload) are closed; the continuous PC submit (Fork A) is the next campaign.

A consolidation, because this is a natural stopping point. Over this run the RK3576 NPU went from a month-long dead
wall to a single, precisely-located gap:
- Multi-task ENGAGE: solved. Dispatch the graph as N sequential single-task kicks (task_number=1 each), not one
  task_number=N PC submit. Every unit engages on every kick.
- The chain FEATURE path: solved. Skip the per-kick pp_state_init (POINTER_PP_CLEAR cooled the on-chip buffer);
  the chained layers now DMA their input and run real MACs.
- The chain WEIGHT path: solved for the DEPTHWISE layers (small weights fetch per kick), NOT for the POINTWISE
  layers — their weight DMA never fires (wt_rd=0), so a pointwise layer computes weightless (bias → relu → the
  output zero-point) and the graph's output collapses.

The pointwise weight is the one remaining piece, and it is architectural. The pointwise config is byte-identical
to the vendor's, so it is not the command stream. The two cheap board levers are now clean negatives:
- **C (CBUF weight-bank capacity)**: giving the pointwise a bigger CBUF WEIGHT_BANK count — 1 and 8 both — does
  not move wt_rd off 0. The vendor uses WEIGHT_BANK=0 (default) and it works, so it is not a regcmd capacity knob.
- **B (on-chip weight pre-load)**: concept-tested and CLOSED. Added a `pw_weight_sram` knob that stages each
  pointwise task's weights into the on-chip NBUF (map 0x3fe80000 → IOVA 0xfff00000) and repoints 0x1110 there.
  The board diagnostic showed the staging never fired: `iommu_map(0xfff00000)` fails (`pw_mapped=0`) — not the
  32-bit-aperture overflow (shrinking the map to 256 K didn't help), so it is a conflict: our Mesa BOs occupy
  that range in the whole-graph domain (they run up near 0xffff0000). Worse, the repeated failed map corrupts
  the domain and the chain regresses to all-0x00. And the NBUF is a fixed HW window — a prior test showed an
  arbitrary IOVA for the weight source doesn't move the CMAC (only the exact 0xfff00000 window does), which is
  exactly the range our BOs sit in. So the on-chip preload can't deliver: the one window that works is occupied,
  an arbitrary one doesn't, and forcing the map damages the IOMMU. Combined with the prior audit (weights via
  NBUF don't reach the CBUF), B is closed.

So the mechanism is settled: the vendor runs the graph as one **continuous** PC submit, and while a layer
computes the PC **pre-stages the next layer's weights into the on-chip buffer**. The depthwise's small weights
we can fetch per-kick; the large pointwise weights genuinely need that pipeline pre-staging, which sequential
kicks don't have. Closing the chain therefore needs **Fork A**: make the continuous multi-task PC submit engage
AND iterate all tasks — which is the wall the sequential kicks routed around ("1/29 then stuck": the units
engage but there is no completion handshake to advance the PC to the next task, and a stall cascades into a
dangerous shared-IOMMU reset / -14). That is register/microcode-level, below the online NVDLA docs, so Fork A is
its own campaign: read the NVDLA RTL (github.com/nvdla/hw) for the PC/executer task-iteration completion logic,
or fall back to extract/replay. Everything up to that one seam works. (Kernel: rk3576-warmchain d54b57d94;
mesa ROCKET_WT_BANK / ROCKET_OUT_SHIFT_ABS diagnostics left in tree.)

## 2026-07-03 (latest, corrected) — Fork A first move: the chain is no longer dead. Skip the per-kick pp_state_init and the chained layers finally engage and DMA their input — but the weight path is still stale, so the CMAC accumulator is empty. The wall became a slope; the FEATURE side is fixed, the WEIGHT side is next.

The chain needs the on-chip buffer warm across layers, which the sequential kicks were cooling. The suspect
was pp_state_init: the kernel re-runs it (S_POINTER group reset + POINTER_PP_CLEAR + the degenerate DS1 default
into both groups) at the head of EVERY kick, and the vendor never does this per task. POINTER_PP_CLEAR resets
the ping-pong so a chained task reads a cleared group instead of the buffer the previous task wrote. And each
task's own regcmd already arms its S_POINTER (mesa writes 0x1004 per task), so the first kick's pp_state_init
is all that's needed for the cold-start engage.

So: run pp_state_init only on the FIRST task of a job, skip it on the within-job re-kicks (rocket.wg_warm_chain).
Board result, MobileNet whole-graph:
- Engage is intact (exec_ever=0xf on every kick), conv0 still computes (distinct=239).
- And for the FIRST time the chained layers are NOT flat zero. Where every layer after conv0 used to be
  distinct=1 / all 0x00 (dead, no DMA, no MACs), they now engage and move: task 1 is uniform 0x80 (not 0x00),
  task 3 is distinct=3 with real values (0x0d/0x7f/0x80), task 4 distinct=4; one chained layer shows
  top dt_rd=50176 / wt_rd=72 (it DMA'd its input and weights) and core dt_wr jumped from 25088 to 100464
  (4x the MACs). Data is flowing across layers now.

It is not correct yet, and a follow-up diagnostic corrected my first read of *why*. The chained outputs
saturate to the output zero-point (0x80/0x7f), so the final result is still degenerate (Top-1 index 0). I first
called this "computes, wrong scale" — a requant problem. **That was wrong.** Forcing the chained-layer OUT_CVT
shift down to an absolute 12 (`ROCKET_OUT_SHIFT_ABS=12`, amplifying the requant by ~2^10 vs the computed
shift 17-25) did not move the output off the zero-point at all — task 1 stayed uniform 0x80, tasks 2/4 stayed
distinct=2 at 0x7f/0x80. If there were a real accumulator being crushed, amplifying it 1000x would light it up;
it didn't. So the chained CMAC accumulator is **empty or negative** (relu'd to zero → output = out_zp), not a
non-zero MAC scaled wrong. Same wall MidG971 is on with RK3568 ("the MAC is empty, the zero-rail is upstream of
the SDP").

The clue is in the counters: some chained layers show **wt_rd=0** — they DMA their input but never fetch their
weights (task 2 and task 4 wt_rd=0, while task 1/3/5 read 36/128/72). A conv with no weights accumulates only
the bias, which after the ReLU collapses to the output zero-point. So warm-chain fixed the *feature* path (the
chained layers now read their input) but the *weight* path is still broken — a sibling of the on-chip-buffer
staleness the feature side had. The next lever is exactly that: why the chained layers' weight fetch doesn't
fire (weight-reuse/CBUF vs a fresh DRAM read, weight bank, or the 0x1110 weight address), so the weights reach
the CMAC the way the input now does. (Kernel: branch rk3576-warmchain, commit d54b57d94, off
rk3576-sequential-kick; rocket.wg_warm_chain=1.)

Narrowing the weight-fetch bug (offline vendor-capture diff, 2026-07-04). First guess was `k_word`: the mesa
encoder sets the CNA kernel-extent word to 0 for any k<3 (`k_word = (k>=3) ? ... : 0`), which for a 1x1
pointwise layer emits 0x1024 = 0x0000_003f — I suspected the zero extent stopped the weight DMA. **Refuted by
the vendor's own bytes:** in the captured 24-task chain the vendor's pointwise tasks (0x100c=0) also emit
0x1024 high-half = 0x0000, and their whole weight-config block (0x101c/0x1020/0x1024/0x1030) is byte-identical
to what the mesa encoder produces. So k_word=0 is correct for pointwise and is not the bug. That collapses the
possibilities hard: it is **not the regcmd** (pointwise config == vendor), **not the mapping** (the weight BOs
are mapped — conv0 and the depthwise layers fetch fine), and **not all weights** — the *depthwise* layers, whose
weights are small (k·k·C), do fetch (wt_rd=36/128). It is specifically the **pointwise** layers, whose weights
are large (Cin·Cout), whose weight DMA never fires. That small-fetches / large-doesn't split is the strong clue:
the same "too big for the on-chip buffer in one go, needs an extra mechanism" pattern the feature side hit when
a 112-wide layer wouldn't fit the CBUF and had to be tiled. So the lead is the pointwise large-weight path — a
weight-bank / block-DMA trigger that warm-chain doesn't cover — the execution-state sibling of the feature CBUF
staleness, now pinned to exactly the large-weight case.

Two board levers, both clean negatives, that close the cheap options and sharpen the cause (2026-07-04):
- **cbuf_reset=1 (H/control-only) + warm-chain**: does NOT clear the pointwise weight-valid state (pw wt_rd
  still 0, feature stayed warm). So the weight-valid, like the feature-valid, is coupled to the AXI/MMU reset
  domain (which cbuf_reset=2 touches but breaks translation) — not the H domain.
- **a fresh pointwise WEIGHT_BANK (ROCKET_WT_BANK=1, pw gets a different CBUF weight bank than the depthwise
  before it)**: does NOT force the pw weight DMA either (pw wt_rd still 0). So it isn't a "bank looks valid"
  skip. (Side effect: it did move a *depthwise* layer's output from distinct=3 to distinct=16 — the bank change
  shifts the CBUF layout — but the pointwise weight fetch is untouched.)

That rules out both the reset-invalidate and the bank levers, and points at the real mechanism: the vendor
runs the whole graph as one **continuous** PC submit, so while a layer computes the PC **pre-stages the next
layer's weights into CBUF** (double-buffering). The vendor's pointwise almost certainly shows wt_rd=0 too — it
doesn't DMA at run time, it reads weights that were staged during the previous task. Our sequential kicks have
no such pipeline, so a pointwise layer's weights are never pre-staged and it computes weightless (bias only →
relu → zero-point). warm-chain got the *feature* and the small *depthwise* weights across with per-kick
fetches; the large *pointwise* weights are the one thing that genuinely needs the pipeline. So the pointwise
weight is the last hold-out, and it is architectural: it wants either the continuous PC submit (Fork A's hard
wall, where the pre-staging is free) or an explicit kernel-side weight pre-load before each pointwise kick.
(Mesa: ROCKET_WT_BANK knob added to rkt_regcmd.c for the test; kernel branch rk3576-warmchain unchanged.)

## 2026-07-03 (latest) — forcing a per-job NPU power-cycle to clear CBUF: it fires, but the power domain hangs on the way back up. Fork B (clear the on-chip buffer in software) is now fully exhausted.

The chain needs a cold on-chip buffer per layer. cbuf_reset=1 can't invalidate it and cbuf_reset=2 corrupts
translation, so the remaining idea was the cleanest reset of all: a full NPU power-cycle between layers, which
clears the CBUF SRAM (the next layer starts cold like conv0) AND re-inits the MMU through the resume path's
rk_iommu_enable (force_reset passes on a freshly powered MMU, no -EFAULT). Run each layer as its own job and
force a synchronous runtime-suspend at each completion (added a `force_powercycle` module param, default off).

It took three tries to make the power-cycle actually happen, and the lessons are worth keeping:
- `pm_runtime_put_sync` did nothing: with autosuspend enabled it only runs the idle path and re-arms the 50 ms
  timer, which mark_last_busy keeps pushing out under back-to-back jobs — the NPU powered off once in 185 jobs.
- Even ordering the put before the fence signal and bypassing the suspend's is_idle check wasn't enough — the
  scheduler credits the next job and its pm_runtime_get races the put. The fix is `pm_runtime_put_sync_suspend`
  (bypasses autosuspend), done BEFORE signalling the fence so, with credit_limit=1, no next-job get can race it.
- With that, the power-cycle finally fires: at the first job's completion the log shows put_sync_suspend ->
  "rpm: suspend" -> the genpd printing `npu0 -> OFF`, `npu1 -> OFF`, `npu0 -> ON`.

And then the board hangs, dead, right there. It wedges at `npu0 -> ON` — *before* the device runtime_resume
callback runs (its first dev_info never prints), so the hang is in the genpd power-ON of the NPU domain, below
the rocket driver. The tell is `npu1 -> OFF`: powering down core 0 cascades the *parent* NPU power domain off
(taking core 1 with it), and bringing it back up immediately wedges on the power-ack. The vendor never powers
the NPU down mid-inference — it holds the whole graph on one powered session — so this rapid off/on path is
unexercised silicon, and it doesn't come back. force_powercycle=1 hangs the board every boot; default 0 is
untouched and safe.

So the "cold buffer per layer" hypothesis is still unproven (we hang before the next layer computes), but every
software lever to reach it is now spent: cbuf_reset=1 (no-op), cbuf_reset=2 (breaks translation), power-cycle
(hangs the power domain). Fork B is closed. The way forward is Fork A — one continuous PC submit so the on-chip
buffer stays warm across layers the way the vendor's does — which means cracking the multi-task PC engage the
sequential kicks routed around. (Kernel: branch rk3576-powercycle, commits 22751c4a9 + 5619e39bd + 6aeba36a6,
kept for reference; DANGER: force_powercycle=1 hangs the board.)

## 2026-07-03 (latest) — the chain break is NOT a Mesa bug: our chained-layer regcmd is byte-identical to the vendor's, and the vendor chains layers through DRAM. The wall is CBUF continuity, which the sequential kicks break.

After the sequential-kick engage win (below), the whole graph still breaks conv0->layer1. To settle whether
that is our command stream or the dispatch, I parsed the vendor's own captured 24-task chain (bo00..bo04 +
meta) offline and diffed it against what we emit and against the live CNA registers on the board.

Two things fell out, both decisive:

- The vendor chains layers through **DRAM**, not a magic on-chip path. Every intermediate activation lives in
  one 2 MB buffer (bo2); each layer's CNA input address (reg 0x1088) points at a real offset in bo2, and the
  layer-boundary tasks are *fresh* reads (no CBUF-reuse bit: 0x1038=0x7, 0x103c low half 0), while only the
  within-layer tiles reuse CBUF (0x1038=0x80000007). CBUF is far smaller than 2 MB, so activations genuinely
  round-trip DRAM between layers.
- Our chained-layer regcmd is **byte-identical** to the vendor's. Replaying the vendor's exact task-1 bytes,
  the live CNA registers read back equal to the capture (0x100c=1, 0x103c=0x00380000, 0x1040=0x14000000,
  0x1044=0x00700038, 0x1090=0x1c0, 0x1094=0x3100, 0x1098=0x27d0), with 0x1088 correctly remapped to a
  filled, IOMMU-mapped buffer. And Mesa's whole-graph submit already puts every intermediate tensor in the
  BO set (as an output; the producer's output tensor and the consumer's input tensor are the same aliased
  BO), so the input is mapped and filled. So it is not the command stream, not the addresses, not the mapping.

What's left is the only thing that differs: **execution context.** conv0 is task 0 of the job — a cold start —
and it DMAs its input (`dt_rd=9408`). Every task that is *not* first in the job skips its input DMA
(`dt_rd=0`) and reads an empty on-chip buffer, producing zero. The CNA treats a non-first task's input as
"already staged in CBUF by the previous task." In the vendor's **continuous** single PC submit the CBUF
really is warm from the previous task, so skipping the DMA and reading CBUF is correct; the 2 MB DRAM buffer
is the spill for what CBUF can't hold. Our **sequential kicks** put a full teardown between tasks
(pp_state_init's POINTER_PP_CLEAR, the OP_EN 1->0 cycle, ~30 µs of gap), so the CBUF is "warm-looking but
empty" and the skipped DMA reads nothing.

So the chain needs CBUF continuity, and sequential kicks (which we needed for *engage*) are in tension with
it. Confirming the tension from the other side: forcing the re-DMA with a per-job on-chip-buffer reset does
work but is coupled to address translation — cbuf_reset=1 (control/H only, IOMMU-safe) is harmless but does
NOT invalidate the "staged" state (chained layers still `dt_rd=0`, conv0 still computes, no saturation);
cbuf_reset=2 (touches the CBUF AXI/MMU bank) does force the re-DMA but corrupts translation and saturates.
The CBUF-valid invalidate and the MMU bank are the same reset domain.

Net: the way forward is the vendor's — one continuous PC submit so the CBUF stays warm across layers — which
means cracking the multi-task PC engage (the wall the sequential kicks routed *around*), now knowing that
single-task arming engages and that continuity is what the chain actually needs. Forcing per-task DRAM reads
in the kicked regime is the other fork, but every software CBUF-invalidate lever there is exhausted or breaks
translation.

## 2026-07-03 (later) — the multi-task ENGAGE wall is DOWN: dispatch a job as N sequential single-task kicks, not one task_number=N PC submit

This supersedes the addendum below that concluded "both remaining walls sit below the register surface;
the next real step is the NVDLA RTL." The engage wall did **not** need the RTL. It needed to stop asking
the RK3576 PC to iterate the tasks itself.

The RK3576 PC never engages the compute units for `task_number ≥ 2` (one OP_EN, PC walks the task array).
A single task engages reliably (proven in replay: an isolated conv and an isolated depthwise both compute).
So dispatch a multi-task job as **N sequential single-task kicks**: each kick `task_number = 1`, one OP_EN,
advancing one task per DPU-done interrupt, all inside **one job** with no soft/CBUF reset and no iommu detach
between kicks. Two lines in `rocket_job.c`: `next_task_idx++` (which re-arms the re-kick branch that was
already in the DPU-done handler) and `PC_TASK_CON` task_number = 1. This is the mainline RK3588 model.

Board result, MobileNet whole-graph submitted as one 29-task job:
- Every kick engages — `exec_ever=0xf` (CNA+CORE+DPU+RDMA all set S_POINTER bit16), `rawor` error bits all 0,
  `TASK_CON=0x00010001` (task_number=1), `DATA_ADDR` advancing through all 29 tasks. The re-kick fires.
- conv0 (task 0) reads its external input (`top dt_rd=9408`, `wt_rd=96`), computes (`core dt_wr=25088`), and
  writes a **real** output to DRAM: `buf[1] out task=0 iova=0xfeb2d000 distinct=235 nz=4092/4096`.

The engage wall we had concluded was below the register surface is crossed in the kernel by reframing dispatch.

What remains, now cleanly isolated and standing ALONE: the **conv0→layer1 data handoff**. task1 onward read
nothing from DRAM (`top dt_rd=0`) and output all-zero (`distinct=1`), cascading to an empty final result
(NPU Top-1 index 0 / conf 0 vs CPU 412). This is the same on-chip-buffer-persistence wall from the entry
below — the chained layer's input never reaches it — but it is no longer entangled with engage, and it is
**above** observability: conv0's output is already sitting in DRAM (`0xfeb2d000`, real), and mesa has already
linked the chain (task N out iova == task N+1 in iova). The next lever is to make each intermediate task read
its input from the previous task's DRAM output BO — the SPREAD-per-op path that already computes single layers
correctly (dw112 `distinct=213`), now inside one engaging job. That is a mesa WG-packer / per-task input-address
fix, not a register mystery. (Kernel: branch `rk3576-sequential-kick`, commits 86457835b + 718707939.)

## 2026-07-03 — the depthwise is not a silicon wall: the "computes nothing" was a stale on-chip-buffer reuse, and it reproduces with the vendor's own bytes

This overturns the two 2026-07-02 entries below ("the depthwise is a wall of its own"). The way to
settle "is this our software or the silicon" was to stop generating command streams and instead replay
the *exact bytes the vendor's stack submits*: capture one operation's payload at runtime (the command
stream + input/weights/bias, byte-for-byte) and feed those same bytes through the mainline rocket driver.

- A standalone depthwise (the vendor's captured dw112, tiled into 6 pieces), replayed as 6 single-task
  jobs, **computes** — it engages, reads its input from DRAM (`dt_rd=20384`), and writes a rich output.
  So the depthwise is **not** a silicon wall; "a single-task depthwise does no MACs" was wrong.
- The multi-task version of the *same* bytes (one job, task_number≥2) still walls (never engages). So the
  multi-task engage wall is real and lives in the kernel's PC drive — same bytes, only the submit grouping
  differs.

Then the real puzzle. In Mesa's Path B (each row-tile its own single-task job) conv0 computes but the
depthwise after it reads nothing (`dt_rd=0`) and outputs zero. To isolate it cleanly I captured the
vendor's 4-layer chain (conv0→dw1→pw1→dw2) and replayed the whole thing spread. The result is decisive:

- conv0, which reads the **external input**, DMAs it (`dt_rd=9408`) and computes.
- every **chained** layer, which reads a previous layer's **intermediate** output, reads nothing
  (`dt_rd=0`) and produces nothing — the on-chip buffer ends up holding only conv0's output.

This reproduces with the vendor's own bytes, so it is not a Mesa bug. And the chained depthwise's command
stream is byte-identical to the standalone depthwise's (same buffer-reuse bit, off) yet one DMAs and the
other doesn't. So whether a layer fetches from DRAM or reuses the on-chip buffer is **not in the command
stream** — it's the on-chip buffer's entry-valid state. The vendor runs the whole graph as one submit, so
each layer's input genuinely still *is* in the on-chip buffer from the previous layer, and reading it there
(no DMA) is correct. Path B ends each layer as its own job, the buffer isn't persisted, the next layer
reuses a stale/empty buffer and gets zero. **That is the whole conv0→depthwise wall.**

Confirming it: a per-job on-chip-buffer reset (`rocket.cbuf_reset=2`) forces the chained layers to re-DMA
— they go from `dt_rd=0` to `dt_rd=20384` and start writing. But that reset also disturbs the buffer's
address-translation bank and the driver doesn't re-establish it per job, so every layer's output saturates
(all `0x7f`/`0x80`); a stronger reset kills everything. Mechanism confirmed, blunt hardware reset can't fix
it cleanly.

The takeaway is architectural: this NPU is built for whole-graph execution, layers chained through the
on-chip buffer. Path B (independent jobs, DRAM round-trips) fights that design — the chained-layer command
streams want to read the on-chip buffer, and forcing a re-fetch needs a buffer invalidate the hardware only
exposes via a reset that breaks address translation. So the way forward is the vendor's own: run the whole
graph as one submit and crack the multi-task engage wall — now with the byte-exact replay as a tool to see
exactly where the engage breaks.

Two direct fixes tried and ruled out. Forcing the chained layer to re-fetch with a per-job on-chip-buffer
reset corrupts *any* compute, not just the chain — a lone conv goes from byte-exact to maxdiff 255 —
because the reset disturbs the buffer's address translation and re-establishing it dies (`-14`). And
writing the vendor's ENABLE_MASK from the CPU to force the multi-task engage just hangs the board (that
register is already written by the command stream, so a raw CPU write to it is redundant and wedges the
bus). So neither the reset nor the enable-mask is the lever. Nor is the on-chip-buffer bank: giving the
chained layer a different data-bank offset (CBUF_CON0 FC_DATA_BANK) leaves it at `dt_rd=0` — the reuse
isn't a command-stream field at all (DATA_REUSE is already 0). So the trigger for "reuse vs re-fetch" is
the on-chip buffer's entry-occupancy *state*, left by the previous layer, with no clean register lever.
That is where this stops being crackable by knob-sweeping: the fix needs the CBUF entry-management
semantics (the NVDLA CDMA/CBUF spec this NPU derives from), not another guess.

The other wall — whole-graph, where the layers *do* chain through the on-chip buffer — has its own
below-observability stop: the multi-task program counter iterates the tasks but the compute executers
never start (the engage bit never sets). The NVDLA programming guide gives one concrete rule — op_enable
must be issued in reverse (downstream-first) order — but reversing it changed nothing; and once the
per-job pointer init is on, the geometry *does* latch into the executer's group and the pointer *is*
armed, yet the executer still won't start. So both remaining walls (the buffer-reuse trigger, and the
executer start) sit below the register surface the online NVDLA docs describe; the next real step is the
NVDLA RTL, not another register guess. Everything up to here — the depthwise being real, the stale-buffer
mechanism, the exact walls — is characterised and reproducible.

## 2026-07-02 (live config) — the depthwise is fully, correctly configured and engaged, and still computes nothing. Not a config bug.

Chasing the intuition that this is software, not silicon, I dumped the depthwise tile's *live* registers
(what the hardware actually holds mid-run, not the command stream I send) and lined them up against a
convolution that does compute. Everything is right:

- **Output writer (DPU): configured** — real destination address, correct output geometry for the tile
  (`0x4018=0xfea69000`, `0x4024=0x59`=89 rows). It is set up to write.
- **Input engine (CNA): configured for depthwise** — the depthwise-mode bit is on (`0x100c=1`), the
  convolution control and the weight byte count (`0x101c=0x240`=576, correct for this depthwise) are right.
- **MAC array (CORE): configured** — output-channel count and the rest match.
- Weights were DMA'd in, the units are engaged (the executer bit is set), and the input is being read.

And the depthwise still writes nothing — an *exact* zero, not a wrong non-zero. A wrong non-zero would mean
the MAC ran with the wrong setup; an exact zero means the MAC array did no work at all. So there is no
visible configuration bug: every register the driver can read is correct and live. Two things this rules
out for good: it isn't a config mistake, and it isn't the engage wall either — the depthwise tile *does*
engage; engaging and computing are separate, and for the depthwise the second doesn't follow the first. The
op is set up perfectly, wakes up, reads its input, and produces nothing. The vendor's depthwise computes
only as a multi-task job; a single-task depthwise, however perfectly configured, does no MACs. That
single-task-vs-multi-task line is the whole remaining mystery.

## 2026-07-02 (Path B) — routed around the multi-task wall, fixed two real bugs, and the depthwise turned out to be a wall of its own after all

The plan was to never hand the hardware a multi-task job: the wide layers only tile because the on-chip
buffer holds one row-window at a time, so emit **each row-tile as its own single-task job** (Mesa,
`ROCKET_TILE_JOBS`) and let the kernel chain them. Single-task jobs engage reliably, so this should sidestep
the multi-task engage wall. Chasing it down found two real bugs and then the truth about the depthwise.

**Bug 1 — a double-free (heap corruption).** With every tile a separate job, the per-op input/output BO-handle
arrays got freed once per tile-job in cleanup — an N-free for an N-tile layer. That corrupted the heap and
hung the run (a userspace timeout, no output). It was a latent bug in the existing "spread" path, only ever
triggered once tiled layers started using it. Fixed (each job owns its handle copies). After the fix, **conv0
computes under Path B** (a real feature map, `core dt_wr=25088`) — so a submit of ~30 single-task jobs is
fine; the hang was purely the double-free.

**Bug 2 — a ping-pong split.** The single-task depthwise tile came up with its producer on buffer group 0 and
its consumers on group 1, so the consumers read the empty half and wrote zero. The cause is a pointer-ping-pong
enable bit that auto-advances the consumer pointer; arming the tile with that bit off (`S_POINTER=0x04`,
executer-enable only) lined all four units up on group 0 — confirmed in the registers: `cna/core/dpu/rdma
sp = 0x00010004`, all engaged, all aligned.

**And the depthwise still drew zero.** Fully aligned, all four units engaged, reading its input — and the DPU
wrote nothing (`dt_wr` never moved past conv0's 25088; the tile output stayed `0x00`). So the ping-pong split
was a red herring: fixing it changed nothing. With both confounds removed — the multi-task engage *and* the
ping-pong — what's left is exactly the wall from before: **the depthwise-mode op does not fire its output
write as a single task, regardless of alignment, engagement, or operands.** The vendor's depthwise computes
*only* as a multi-task job (per-task re-arm); ours won't engage multi-task. So the depthwise is blocked both
ways — single-task, the DPU write never fires; multi-task, the units never engage — and both live below the
registers. Path B routes around the engage wall for ordinary convolutions and fixed two genuine bugs, but it
does not carry the depthwise. The one lever left is a hardware trace of what the vendor's DPU does per task in
the multi-task path that a single task doesn't.

## 2026-07-02 — the two walls collapse to one: multi-task engage. The depthwise is not a separate wall; the gap is below observability, and the only untested difference left is firmware

Added a per-unit engage-state dump to the kernel (each unit's `S_POINTER` [bit16 = executer engaged, low
nibble = ping-pong group] and `S_STATUS`, at rest and right after the go-pulse) and compared a working run
to a failing one, both as the first inference after a clean boot so nothing is confounded by the
second-inference degradation.

**The multi-task wall is an engage failure.** A byte-exact conv forced to `task_number=2` (only that field
changed):

```
working (task_number=1): all 4 units sp=0x0001000f  (bit16 SET = engaged),  STAT=0x0c, core dt_wr=12800
failing (task_number=2): all 4 units sp=0x0000000f  (bit16 CLEAR = not engaged), STAT=0x05, dt_wr=0
```

So `task_number>=2` makes the sequencer advance its task counter and report "done" while the compute units
never engage — not one of them sets bit16, the output writer never writes a byte.

**The depthwise looked like a second wall, then wasn't.** As a (vendor-never) single full-height task the
depthwise *does* engage (bit16 set on all four) but splits the ping-pong: the CNA producer advances to
group 1 (`0x0f`) while the consumers stay group 0 (`0x0e`), so the consumers read the empty group and the
output is zero, while a standard conv keeps all four aligned and computes. That's a concrete, register-level
cause — but it was only ever seen under `NO_DW_TILE`, a shape the vendor never emits (it always row-tiles a
112-wide depthwise). So I checked how the vendor's *tiled* depthwise handles the parity, two ways: its
command stream arms every unit to group 0 (`0x0e`) on **every** task (no alternation), and — instrumenting
the vendor's own driver and running it on the board — its multi-task depthwise settles with all four units
aligned at group 0 and computes (`core dt_wr=25088`). It never uses the producer-ahead pattern. So the
split is a `NO_DW_TILE` artifact: the vendor avoids it by tiling into small tasks and re-arming group 0 each
task. **The depthwise is not a separate silicon wall — it's just the first layer forced to be multi-task.**

**Where it ends, honestly.** Everything now reduces to one thing: the units engage per iterated task on the
vendor and don't on the open driver — with a per-job setup I've matched to the vendor byte-for-byte (the CPU
arming, the command-stream `S_POINTER` writes, the init sequence, the go-pulse), and single convolutions
prove the datapath is addressed correctly. The vendor engages its units from the `S_POINTER` arming plus one
pulse with no in-stream enable; the open driver's units only wake from an in-stream enable that restarts the
sequencer, so it can't iterate. Trying to catch *how* the vendor re-engages between tasks, on the board, the
vendor finishes a two-task depthwise in microseconds — faster than a CPU register poll can sample — so the
per-task re-engage is below what software can observe on either side. Software knobs, static command-stream
comparison, and a live vendor capture are all exhausted. The one structural difference left untested is
**firmware**: the vendor stack boots Rockchip TF-A + OP-TEE (NPU clock/power via secure SMC calls), mainline
boots neither, and a secure-world NPU init is exactly the layer a vendor capture can't isolate. That's the
next dig, and it's a big one.

**Update — firmware ruled out, and the real way forward.** I did the dig: built an image with a mainline
RK3576 OP-TEE port (BL31 + BL32, TZDRAM reserved in the DTB) and booted the same rocket kernel on top of it.
OP-TEE really ran — its own secure-world banner prints on the console, the DDR firewall is live — and the
multi-task job failed *byte-for-byte identically*: not one unit engaged, nothing written. So it isn't the
presence of the secure firmware either. The multi-task engage difference is below what software can observe
on either side; without a hardware trace it isn't reachable, and it's the one thing between here and a
running MobileNet.

But "can't crack the multi-task engage" is not "can't run MobileNet." The wall only bites *multi-task* jobs
— a job carrying more than one task. Single-task convolutions engage and compute reliably; that's proven.
The wide layers only need multiple tasks because one row-tile at a time is all the on-chip buffer holds — so
the fix is to stop packing the tiles into one multi-task job and instead emit **each row-tile as its own
single-task job**: its own input rows staged from DRAM, its own weights, its own slice of the output,
chained by the kernel like the per-op path already chains layers. It costs re-staging weights per tile (no
reuse) but every job is then a task-count of one, which the hardware runs. That's the concrete next build —
in Mesa, not the kernel — and it routes around the one wall left standing instead of trying to break it.

## 2026-06-30 (later) — on-chip weight SRAM ruled out; full register diff = vendor superset; multi-task wall confirmed by controlling inference order

Continued from the two-walls result below. Three things settled by board tests, judged by the output buffer
and the DMA byte counters (`core dt_wr`).

**1. On-chip weight SRAM (the vendor's "nbuf") is NOT the depthwise lever.** Made the kernel stage each
depthwise layer's weights into the 1 MB on-chip NPU SRAM (the exact region the vendor uses) and repoint the
CNA weight-source register at it. This needed reserving the on-chip IOVA window from the BO allocator first
(the high-IOVA BOs collided with it: `iommu_map ... ret=-98`). After the reserve it works — the log shows all
13 depthwise layers staged (`staged weights 0x...->SRAM`), `conv0` still computes — yet the depthwise output
stays exact `0x00`, the weight staged 10 ms before the op ran. So the weight *source location* (DRAM vs
on-chip) changes nothing.

**2. The full register diff is a vendor superset — no missing register.** Compared every register the open
driver writes for the depthwise (CNA + CORE + **DPU + DPU_RDMA**, not just the conv-engine block) against the
vendor's. The open driver writes a strict **superset** (138 vendor entries, 142 ours; the 4 extra are the
per-unit enable writes). Every value difference is explained by tiling geometry, the sample model's different
quantiser, or those enables. The one unexplained config word (`CNA 0x1080`) was forced to the vendor's value
— the depthwise still output zero. The depthwise command stream is exhausted.

**3. The multi-task wall is real — confirmed by controlling for inference order.** A long-standing confound:
a *second* inference after boot degrades to zero on its own (inherited dirty state), so any A/B where the
"broken" case ran second is suspect. Reversed it — ran `conv2d-cal` with the PC task-number forced to 2 as
the **first** inference after boot, valid submit:

```
wgsubmit: TASK_CON=0x00010002 DATA_ADDR=0xffef6000 DATA_AMOUNT=0x49   (task_number=2, valid)
cnalive:  exec_ever=0x0   (not one unit engaged; a working single task = 0xf)
perf:     core dt_wr=0    (the DPU never wrote; force=0 single task = dt_wr=12800, byte-exact)
buf out:  distinct=1      (zero)
```

Only the `TASK_CON` task_number differs from the byte-exact single-task run, and `task_number>=2` takes the
output to zero with the units never engaging — even on a clean first inference. So the multi-task wall is not
the second-inference confound; it is real. (`dt_wr` also separates the two: the multi-task wall is `dt_wr=0`,
the units never fire; the second-inference degradation is `dt_wr>0` but the output is wrong.)

**Mechanism (from the vendor's own driver source).** The vendor engages the units with no enable-mask
register write at all (that register is out-of-map on the vendor — reading it oopses) and **no in-stream
enable in the command stream**: just one `PC_OP_EN=0x1` pulse plus each task's in-stream `S_POINTER` writes,
which the PC applies per task. The init sequence matches ours byte-for-byte. The open driver's units, by
contrast, only engage from an **in-stream broadcast enable** (a write to `PC_OPERATION_ENABLE` inside the
command stream) — and that write *restarts* the PC, so with `task_number>=2` the units never latch. Drop the
in-stream enable to match the vendor and the units don't engage at all. So the gap is not the enable-mask
register, not the init, not the submit sequence (all identical) — it is the silicon-level question of why our
units need an in-stream `PC_OP_EN` to engage while the vendor's engage from the `S_POINTER` arming + the
pulse. Software knobs are exhausted; the next data needed is a vendor capture of the per-task engage during a
real multi-task run.

## 2026-06-30 — two separate below-the-register walls: the depthwise op, and multi-task dispatch

Chased whether the depthwise zero is actually the multi-task dispatch wall — the depthwise is row-tiled
into a `task_count=2` job (standard convs are `task_count=1` and compute). Two clean board tests, judged
by the output buffer:

- **Multi-task PC probe** (conv2d-cal duplicated into 2 *real* identical tasks): a single task is
  byte-exact; 2 real tasks are degenerate for **every** OP_EN variant (per-unit `0x1d` / `0x1`, fully
  stripped). The clean run: the units engage (all four `bit16` set), the geometry latches (real `DS1`,
  not the ping-pong default), the PC completes task 0 — then raises `PC_DONE`, never advances to task 1,
  output zero. Every observable signal equals the working single-task run **except `TASK_CON`
  task_number (1 vs 2)**. So `task_number>1` breaks the compute through something no register exposes.

- **`ROCKET_NO_DW_TILE`** (emit the 112-wide layer as one full-height task instead of row-window tiles →
  `task_count=1`): the depthwise is now a single task and **still** outputs exact `0x00` — not garbage,
  so not a CBUF overflow — while the standard convs on the same run compute. So the depthwise zero is
  **NOT** the multi-task wall; it fails as a single task too. It is depthwise-*mode* specific.

- **Clean single-task depthwise** (`NO_DW_TILE`): inert to all three operands — weights (filled with a
  constant), input (a real feature map from conv0), and a forced bias-add jammed straight into the
  requant output stage. None move the output off zero. The op writes nothing.

So there are **two separate walls below the registers**: the depthwise-mode op (writes nothing, the
depthwise layers) and the multi-task PC (`task_number>1` breaks the compute, the whole-graph + tiled
layers). Both have command streams byte-identical to the vendor's; software probing is exhausted on the
depthwise. The one structural thing the vendor does that the open driver doesn't is **park the weights
in the 1 MB on-chip NPU SRAM** — RK3576 is the only chip in the family wired for it. That's the next dig,
and it's in the kernel.

## 2026-06-29 — per-op path: standard convs byte-exact, but the DEPTHWISE op writes no output (below register observability)

Whole-graph (WG) single-job dispatch is an open problem (the unit engage/complete handshake — units
either compute but the in-stream OP_EN restarts the PC, or the PC iterates but the units don't engage;
exhausted the knobs). So pivoted to **per-op** (one DRM job per layer) to reach a *correct* end-to-end
first. All results below are from board tests judged by the output buffer (the only reliable oracle).

**per-op chaining is sound.** mesa shares each intermediate tensor's BO by index; the kernel serialises
the N per-op jobs via dma_resv implicit fences (job N+1 waits for job N). On a clean board conv0
(standard firstconv) computes — `out distinct=242`, a real feature map — and conv2d-cal is byte-exact.
(The old "conv0 ~10% race" was a confound: a boot script auto-ran a WG MobileNet that wedged the engine
before every test; disabling it made conv0 reliable.)

**MobileNet dies at the first depthwise (layer 1).** Per-layer dump: `conv0 out distinct=242` (real) →
`dw1 in distinct=238` (= conv0's real output, so the chain propagates) → `dw1 out distinct=1, all 0x00`.

**The depthwise op produces no output — and it is not mesa's doing.** Three board tests:
1. *command stream*: mesa's depthwise CNA+CORE config is **byte-identical to the vendor's** for the same
   conv (49 registers: `100c=1` dw-mode, `1018` CONV_CON, `101c=0x240` weight bytes, `3018` CORE, …).
2. *weights* (`ROCKET_DW_WTEST`): fill the whole depthwise weight buffer with `0x7f` → `dw1 out` still
   `0x00`.
3. *bias-add* (`ROCKET_DW_ATEST`): force the requant add operand `A=0x2000` (output = `requant(MAC+A)`,
   so A reaches the output regardless of the MAC) → `dw1 out` **still** `0x00`.

Input, weights, AND a forced bias-add all change nothing → the depthwise op never executes its
compute+write; the output stays `0x00`. Standard convs write correctly on the same DPU/kernel, with all
operands staged identically. So it is **depthwise-mode-specific, below register-probe observability, and
not the command stream / weights / layout / requant.**

**Net.** Byte-correct end-to-end MobileNet on RK3576 rocket is blocked by a depthwise-mode execution
wall (same class as the WG engage wall) — not reachable from mesa, whose every input is verified
identical to the vendor. Remaining paths: a hardware execution trace, or the on-chip weight residency
the vendor uses (the 1 MB NPU SRAM + `cache_sgt`, which RK3576 is the only config to wire up and rocket
lacks). Tools added: `ROCKET_DW_WTEST` / `ROCKET_DW_ATEST` / `ROCKET_DUP_TASK` (mesa),
`rocket.wg_force_tasknum` (kernel), `S98mndump` (auto per-layer buffer dump at boot).

## 2026-06-27 (SOLVED) — conv2d is byte-correct; the dominant bug was the C scale fixed-point, not the float surface

`conv2d-cal` (per-tensor, `in_zp=128` — the model called "welded-shut / blob-only" below) now matches the tflite CPU
reference: **100% byte-exact vs the relu reference over the whole output** (constant input maxdiff=0, ramp maxdiff=1 =
int8 rounding). The "float surface is the dominant, non-derivable error" conclusion below was wrong — the float surface
was never the problem. Three derivable fixes, all found by trial-and-error env-knob sweeps judged by the maxdiff oracle:

1. **ABC-buffer C scale fixed-point.** Emit `C = round(16*rel)` (Q4), not `round(16384*rel)` (Q14). The BS stage applies
   C as a raw multiplier then shifts right by 4, so 1.0 = 16; the `0x4000` over-scaled by 2^10 and railed every output
   to 0/255 — the long-standing "all grey / saturated" wall. C sweep: C=16384 → 50% saturated, C=1 → 0%, C=16 sharply
   optimal (exact jumps to 94%).
2. **CNA pad value (`0x1084`) = `input_zero_point - 0x80`,** not the hardcoded `0xffffff80`. `0xffffff80` (pad with 0)
   is correct only for `in_zp=0` (image input). For `in_zp=128` the padded taps added a wrong term → the whole output
   **border ring** was wrong (the last ~6%; the interior was already 100% exact). A control run with the old value
   reproduced the broken border.
3. **Bias operand `A = bias_in`** for `in_zp=0x80` (drop the `0x80` a_scale and the `sw` term).

`wt_zp` is corrected by the `B` term already in the ABC buffer (the HW multiplies it by the per-output input-sum) — not
by packing it into the weights. The HW also applies a **RELU on the accumulator** (negative → out_zp): correct for
MobileNet's ReLU6, only visible here because `conv2d` has no activation. Patch:
`mesa-patches/rk3576-conv2d-int8-WORKING-2026-06-27.patch`. Next: MobileNet (per-tensor, every layer ReLU6).

## 2026-06-27 (next wall) — MobileNet runs all 28 layers on the NPU for real, but the dispatch ping-pong zeros it

With conv2d byte-correct, ran the full MobileNet: NPU output all-zero (0/1001 nonzero). First verified it's
**REAL NPU, not a CPU fallback**: 28 hardware jobs (regcmd[1..28], ~30ms each, ~0.84s total, all four units
engaged), NPU invoke 830ms vs CPU 70ms. So the conv stack genuinely runs the whole network and returns zero.
Cause = the **S_POINTER ping-pong producer/consumer parity**: each unit reads geometry (h,w) from one of two
banks and a state machine flips the bank per task; the producer writes the dimensions into one bank, the
executer reads the other (empty), so every layer runs on h=0 → zero. The **mesa-side S_POINTER value is
irrelevant** (ROCKET_SPTR=0x00/0x30/0x0e all identical all-zero) because the KERNEL re-arms S_POINTER in
pp_state_init/hw_submit, overriding the regcmd → the fix is KERNEL-side, needs a kernel rebuild. Progress vs
months ago: the PC now iterates all 28 tasks (was ~1, stalled). Red herrings ruled out: cnalive `ds0 w=0` and
`cube=` are bogus parses (conv2d-cal works with them too); the DPU output geometry (DST) is correct. Next:
kernel PP-parity (rocket_core.c pp_state_init / rocket_job.c hw_submit). add.tflite (has an ADD op) crashes the
board, so it is not a usable minimal multi-task test — need a pure 2-conv model.

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

## Off-board structural map of the SDP coefficient buffer (2026-06-25, no board)

Done entirely on the host (aarch64) from the one live capture we already have on disk —
`dirty/npu-test/vendor-bias.bin` (20800 B, vendor stack running `conv2d.tflite`) — plus
conv2d's known int8 weights/bias/quant. Reusable check: `vendor-capture/ana_coef.py`.

- **Buffer = `[ABC | float surface]`.** ABC = 16 groups × 64 B (8 oc/group): `A[oc]` int32 @0,
  `B[oc]` i16 @32, `C[oc]` i16 @48. Float surface = the remaining 4944 f32; every nonzero value
  is an integer multiple of `wt_sc`.
- **`A` is derivable.** `A[oc] = -M·(bias[oc] - in_zp·sw[oc])`, `M = in_sc·wt_sc/out_sc`,
  `sw[oc] = Σ(wq-wt_zp)` — corr **-0.996**. A is the per-channel requant **bias-correction** term.
- **`C` varies per output channel (10489–16384, 57 distinct over 128 oc) — for a *per-tensor*
  conv.** A genuine per-tensor requant would emit ONE constant multiplier. Varying `C` means the
  **vendor toolkit silently re-quantises the per-tensor conv into a per-channel one** with
  compiler-chosen scales. That is the *mechanism* behind "blob-only": the float surface is
  per-channel **re**-quantised weights, and the chosen per-channel scales are toolkit-internal.
  A genuinely **per-axis** model (MobileNet) carries explicit per-channel scales, so there the
  same surface is derivable. (Confirms the earlier per-tensor/per-axis split from first principles.)
- **The `.rknn` does NOT carry the assembled live surface.** Live float surface vs
  `conv2d_rk3576.rknn`@33488: **14/4944** floats match — the earlier "match" was a 16-float
  signature coincidence. librknnrt assembles the surface at runtime. ⇒ the surface's exact bytes
  and its **layout cannot be obtained off-board from any .rknn**; only a live (board) capture has it.
- **The surface layout ≠ the weight-DMA layout** (`dirty/vendor_cap/generic_slot_map.npy`):
  among the surface's 742 nonzero slots, **0** match the weight order. It is its own sparse/padded
  layout.
- **Host toolkit limit:** on arm64 `rknn.load_tflite` is unsupported ("unsupported tflite on arm64
  platform"); only the ONNX path converts. And since the .rknn lacks the live surface anyway,
  cracking the per-axis surface layout requires a **board capture of a per-axis conv**, not more
  host conversions.

**Net:** the *derivable* half of the buffer (A = bias-correction × M) is now pinned off-board; the
non-derivable half (per-channel `C` scaling + the float-surface layout) is confirmed to need a live
per-axis capture. The decisive next board step is to capture the vendor's coefficient buffer for a
**per-axis** conv (or for `conv2d-cal`), then feed it verbatim and read maxdiff — no derivation guesswork.

## Clean per-axis board captures (2026-06-25): float surface ≠ weights, but the requant (ABC) IS derivable

Captured the vendor's live coefficient buffer for three **position-encoded** per-axis convs (so the
weights spell out their own coordinates) + per-tensor `conv2d` for contrast, through the vendor rknn
stack (`vendor-capture/{gen_perax,run-coefcap}.py`, full BO dump, coef offset read from the regcmd's
`0x5020`/`0x5024` IOVAs — not guessed). Models: `pw_ic` (1×1, weight[oc,ic]=ic+1), `pw_oc`
(weight=oc+1), `dw_k` (3×3 depthwise, weight=ky*3+kx+1). Decoder: `vendor-capture/ana_perax.py`.

**The float surface (0x5024) is NOT the dequantised weights — not even for per-axis.** Decisive: `pw_oc`
weights are `oc+1`, so a weight copy would show the 128 constants `1..128`; the float surface has **8
distinct values** total (`{-2.25, 0.0078, 0.016, 0.024, 2, 22, 219}`). `dw_k` (weights `1..9`) gives
**384** continuous values, nothing like `1..9`. This **refutes the premise of the per-axis pivot**
(the earlier "the per-channel float surface decodes cleanly to the dequantised weights" — that idg read
was muddled). The float surface is a toolkit-internal structure for per-axis too; its role/derivability
is still open (values look like `in_sc`-multiples / requant terms, but it is not 128 per-channel scales).

**But the ABC requant block (0x5020) is fully derivable for per-axis** — read with the exact offset:
- `A[oc] = M·(in_zp·sw[oc] − bias[oc])` (the bias-correction; constant in these bias=0 / uniform-sw
  models, matching the per-tensor corr −0.996).
- `B[oc] = in_zp − wt_zp = 128` (constant).
- `C[oc]` = the **per-channel requant multiplier, ∝ `in_sc·wt_sc[oc]/out_sc`**: proven by `pw_oc`,
  where `C = 128·(oc+1)` tracks the per-channel weight scale *exactly* (the channel with twice the
  scale gets twice the multiplier), vs `pw_ic` where every channel shares a scale → `C = 16384`
  constant. Derivable straight from the model's per-channel scales.

This also **explains the old per-tensor "C is a blob"**: for a per-tensor conv the toolkit *invents*
per-channel scales (not in the model) → not derivable; a per-axis model *carries* them → `C` derivable.
So the per-axis pivot was right about the **requant** layer (ABC encodable in `rkt_coefs.c`), and wrong
about the **float surface** (not the weights). NEXT: encode the derivable ABC, board-test whether
ABC-alone computes for a per-axis conv (maxdiff) — i.e. whether the float surface is even load-bearing
there — before spending more on the surface.

## Per-axis ABC encoder VALIDATED byte-exact against board ground truth (2026-06-25 pm)

From the clean position-encoded captures, read the per-channel multiplier with the exact regcmd offset
and validated the full ABC against the captured bytes (`pw_oc`, `pw_ic`):

- **A[oc] = 0x80·(Σ_kernel wq[oc] + bias[oc])** — byte-exact. pw_oc: Σwq=16·255=4080 → A=0x80·4080=522240 ✓;
  pw_ic: Σwq=2167 → A=0x80·2167=277376 ✓. This is **mesa's current formula** (rkt_coefs.c:423) — A was right.
- **B[oc] = 0x80 − wt_zp** — constant, mesa already correct.
- **C[oc] = round(2^14 · wt_sc[oc] / max_oc(wt_sc))** — the per-channel requant multiplier. Validated
  **256/256 exact** across pw_oc+pw_ic (`wt_sc[oc]=max|w[oc]|/127`). C is *relative* (normalised to the
  max channel = 2^14); the absolute scale rides the per-layer OUT_CVT shift mesa already computes.

So the per-axis requant is fully specified and proven. **mesa's two bugs:** (1) it emits a *contiguous*
A/D/float layout, but the vendor (and the HW) want the **interleaved `[8×i32 A | 8×i16 B | 8×i16 C]`** per
8-oc group; (2) it never writes **C** at all. Fix = interleaved layout + the validated C.

**Blocker for C:** it needs per-channel `wt_sc[oc]`, but the teflon `pipe_ml` API exposes only ONE
per-tensor `weight_tensor->scale` (rkt_coefs.c:410), and per-axis int8 weights are each normalised to
±127 so the relative scale **cannot be recovered from the weights** — the per-channel scales must be
plumbed from the tflite (per-axis quant params) through the teflon delegate into `pipe_tensor`. That
plumbing + the interleaved-[A|B|C]-with-C emit is the implementation. The **float surface** (0x5024)
role is still open (it is NOT the weights); next board test = does interleaved ABC-with-correct-C
compute with a zeroed float surface, i.e. is the surface even load-bearing for per-axis.

## 2026-06-25 (evening) — per-axis delegates + runs on HW (gate fixed), but the live MAC still doesn't turn over

Pushed the validated per-axis ABC encoder all the way onto the hardware, clearing gates in sequence:
- **The float surface is per-channel DERIVABLE fields, not an opaque blob** (round-2 position-encoded
  captures, `g_bias`/`g_const`/`g_pt`, 5-way cross-model isolation): a **bias field = −bias[oc]** in
  float (`g_bias` shows −300,−400,… = −(oc+1)·100), a per-channel **scale** field, and global constant
  blocks (a 1344-long `in_sc`=0.0078 block, two 64-blocks). The bias formula is decoded; the **tiling is
  intricate/fragmented** (channel-offset, ~3 runs of ~128) and the weight-value placement looks
  data-dependent — the genuinely hard remaining piece. **`g_pt` (per-tensor) is structurally different**
  (ABC region 512B = A-only, no interleaved B/C; float surface = 861 distinct continuous values = the
  toolkit blob), so the per-axis decode does NOT transfer to a per-tensor MobileNet.
- **MobileNetV1 is PER-TENSOR uint8** (every conv: n_scales=1), not per-axis — correcting a premise that
  ran through this whole journal. So a per-axis encoder needs a per-axis model (re-quantise MobileNet, or
  ship per-axis layers).
- **Built a real per-axis int8 tflite with TensorFlow** (`vendor-capture/build_perax_tflite.py`,
  installed TF on the host) — 1×1 pointwise 16→128, weight nscales=128, non-saturating output
  (distinct=206), verified on the host.
- **The rocket driver explicitly REJECTED per-axis** at the support gate (`rkt_ml.c:427`
  `tensor_quantization_supported` returned false when `scales != NULL`), so teflon never delegated it —
  the first board run was a silent CPU fallback (maxdiff=0 but no submit). **Relaxed the gate** to allow
  per-axis weights/bias (the encoder handles them); now teflon **delegates + submits a real NPU job**
  (`rocket dbg submit`, weights BO loaded, `buf wt distinct=247`).
- **And the board's verdict: the conv still does not compute.** NPU output `distinct=1` (constant),
  `maxdiff=127`, `core wt_rd=0`, `ds0=h=0,w=0`. **Identical wall to per-tensor `conv2d-cal`.** So the
  live-mesa MAC failing to turn over is **independent of the coefficient buffer and of per-tensor/
  per-axis** — the validated ABC is necessary but not sufficient. Only the **vendor's exact full buffer
  (replay milestone) computes**; mesa's own ABC + a non-exact float surface (zeroed or dense) does not.

**Net:** tonight cleared the per-axis path end-to-end (encoder validated, gate opened, delegation +
submit working) and the hardware then localised the real live blocker one layer deeper: the conv's MAC
produces a constant — the **CBUF→CMAC / geometry (`ds0=h0,w0`) wall** the vendor regcmd clears and mesa's
doesn't, OR the requirement for the **exact** (blob-tiled) float surface. The coefficient-buffer work
(byte-exact ABC, half-decoded float fields) is correct but sits downstream of this. NEXT: chase why the
live mesa regcmd leaves `ds0=h0,w0` (geometry not latching) vs the vendor's, OR finish the float-surface
tiling — the two candidate live blockers. Patches: `mesa-patches/0002` (encoder) + the gate relax.

## 2026-06-25 (late evening) — the wall is the buffer (not the regcmd); the float surface = derivable skeleton + a data-dependent weight scatter

Two decisive isolations, both judged by the VALID oracle (output maxdiff/distinct on a non-saturating
model — NOT `core wt_rd`, which is a red herring that bit again):

- **regcmd vs buffer.** Fed the EXACT vendor coef buffer (`vendor-bias.bin`) to LIVE mesa (mesa's own
  regcmd) on the non-saturating `conv2d-cal`: NPU output **distinct=256, a rich feature map**. So the
  MAC turns over on the live path with the right buffer ⇒ **mesa's regcmd is FINE; the coefficient
  buffer is the wall.** (maxdiff was large only because vendor-bias is conv2d's ABC fed to cal — the
  ABC out_sc mismatch; the point is the MAC *computed*.) This re-explains every prior "degenerate live
  conv": it was the buffer (float surface), not geometry.
- **float surface = weights?** Per-axis end-to-end test (perax_pw, the TF-built per-axis tflite, now
  delegating): validated ABC + a **dequant-weight** float surface → **distinct=1, degenerate**. So the
  float surface is **NOT** the dequantised weights — clean negative from the valid oracle (kills the
  "second copy of the weights" hypothesis the whole journal carried).

**The float surface dissected (from the 5 position-encoded captures) — it is NOT a fragmented blob:**
contiguous per-channel arrays. ~90% of the nonzero structure is fixed across models (differences are
value-dependent zeros, not placement). The arrays:
- `@2676` len 124: **BIAS array = −bias[oc]**, contiguous, slot = base+oc (g_bias shows −(oc+1)·100).
  **Derivable.**
- `@1216` len 1456: the `in_sc` (=0.0078) constant block. **Derivable.**
- a per-channel **scale** field. **Derivable.**
- `@386`/`@4724`/`@3600`: **weight-VALUE arrays placed data-dependently** — g_const's weight 64 lands at
  `@386`, pw_ic's top weights 14/15/16 land at `@4724`: each model drops its weight values into
  value-sorted/sparse bins. **This is the genuine non-derivable blob — and it is ONLY the weight
  placement, not the whole surface.**

So the wall is precisely localised: the float surface is a **derivable skeleton** (bias = −bias[oc],
in_sc, scale) **+ a data-dependent weight scatter**. NEXT decisive test (answers per-axis derivability):
fill ONLY the skeleton (bias+in_sc+scale), leave the weight arrays zeroed, end-to-end on perax_pw — if
it computes, the weight scatter is NOT load-bearing and per-axis is fully derivable; if it degenerates,
the weight scatter is the (data-dependent) wall. Lesson re-logged: do NOT trust `core wt_rd`; only the
output on a non-saturating, carrier-matched model is the oracle.

## 2026-06-25 (night, close-out) — the per-axis carrier itself doesn't compute richly; the day's wins stand, the validation is blocked on a fresh question

Spent the evening tuning the float surface on `perax_pw` (the TF per-axis tflite) and it degenerated
every time — zeroed, dense dequant-weights, derivable-skeleton, AND a *valid same-shape* buffer
(`pw_oc`'s captured coef): output distinct 1–4 in every case. Contrast: `conv2d-cal` + a *wrong-out_sc*
vendor buffer stays **distinct=256** (rich). So either `perax_pw` is a broken carrier (int8 activations
/ 1x1 / 8x8 path) OR it was simply never handed a *correct* buffer (its own vendor coef, which the
tflite↔rknn arm64 mismatch blocks me from capturing). **Unresolved — and it confounded every per-axis
end-to-end test tonight.** One thing ruled out cheaply: the OUT_CVT offset (`rkt_regcmd.c:345`,
`out_offset = output_zero_point - 0x80`) *does* handle int8 (zp=0 → −128), so int8 output is not an
obvious break.

**Solid, banked results of the day (these don't come undone):**
1. per-axis **ABC encoder byte-exact validated** (pw_oc/pw_ic 1024/1024); support gate opened so teflon
   delegates per-axis.
2. **The wall is the buffer, not the regcmd** — vendor buffer on live mesa → distinct=256 (judged by the
   *valid* oracle, output on a non-saturating model, after relapsing to the `wt_rd` red herring and being
   caught).
3. **Float surface = derivable skeleton + data-dependent weight scatter**, precisely localised: bias
   array = −bias[oc] (@2676 contiguous), in_sc block (@1216), per-channel scale — derivable; the
   weight-VALUE arrays (@386/@4724/@3600) are value-sorted/sparse — the genuine blob, and only that part.
4. The `bufsize` floor fix (small convs under-allocated the float region → OOB).
5. Host toolchain: TF builds+verifies per-axis int8 tflites; capture-decode + byte-validate scripts.

**Two fresh-mind restart paths (both high-risk/precision — do NOT do tired):**
(a) Diagnose why `perax_pw` won't compute richly — is it a broken int8/pointwise carrier, or never given a
correct buffer? (Cleanest probe: get `perax_pw`'s own vendor coef — needs the ONNX→rknn route around the
arm64 tflite-load block + the TF/rknn protobuf conflict, i.e. a separate venv.)
(b) Validate the float-surface skeleton on `conv2d-cal` (the carrier that DOES compute) — needs the
per-TENSOR skeleton decode, with the caveat that per-tensor per-channel scale may be toolkit-invented
(the blob) and not derivable. Both are precision work; tonight was 13 flashes.
