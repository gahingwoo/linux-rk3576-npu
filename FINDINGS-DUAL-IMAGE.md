# RK3576 NPU wall — same-kernel vendor-vs-rocket verification

The chained-task wall (only the first task per power session does real MACs; later
tasks in a `task_number=N` submit engage + DMA input but the CMAC output never
lands) had been chased on the rocket stack alone. This is a cross-check on a **single
mainline-7.1.3 image that boots either the vendor rknpu or the open rocket driver**
on the same board (two DTB variants pick which one binds `npu@27700000`). That makes
every "vendor does X, rocket doesn't" claim testable on one kernel instead of
inferred across two.

Every result below is **measured on this stack**, not transferred from the earlier
rocket-only work.

## Ruled out (with real tests)

| candidate | test | result |
|---|---|---|
| regmap env (genpd/clk/QoS/vdd) | ftrace `regmap_reg_write`+clk+genpd+iommu, cold, vendor vs rocket, set-diff | identical (only non-NPU housekeeping differs) |
| direct writel (NPU block + IOMMU) | per-driver `wtrace` of every readl/writel → absolute phys, set-diff | identical |
| read-based pd-arm | vendor's `readl(VERSION)`+MMU-DTE cycle is a shared pm-domains arm both stacks run | doesn't fix the wall |
| **stale IOMMU TLB** | see below | **doesn't fix — but the project's own fix was a no-op** |
| **data-cache coherency** | see below | **wall is real, not a stale-read artifact** |
| driver submit-register values + order | wtrace with values, vendor vs rocket | match (below) |

## The stale-TLB finding (the big one)

rocket_job.c already diagnosed the wall as stale-TLB — "a reused iova can carry a
previous BO's translation → stale/zero reads → partial (channel-bank) conv output" —
and added `rocket_tlb_flush=1` calling `iommu_flush_iotlb_all()` before each submit.

**That call is a silent no-op.** mainline `rk_iommu` implements neither
`flush_iotlb_all` nor `iotlb_sync` (its `default_domain_ops` has only attach / map /
unmap / iova_to_phys / free), and `iommu_flush_iotlb_all()` skips a NULL callback. So
the TLB was never actually flushed per submit — the diagnosed fix never ran.

Implemented a real one (patch `0025`, `rk_iommu_flush_iotlb_all` → ZAP_CACHE every
bank). wtrace confirms it now fires per submit on both banks:

```
rocket wt w 27702008 00000004   (mmu bank0 COMMAND = ZAP_CACHE)
rocket wt w 27702108 00000004   (mmu bank1 COMMAND = ZAP_CACHE)
```

**Wall persists.** With a real per-submit ZAP, the output BO is still untouched →
stale-TLB is not the root cause. (The `flush_iotlb_all` is a legitimate rk_iommu fix
regardless and is arguably an upstream bug — any RK-platform driver relying on
`iommu_flush_iotlb_all` is silently unflushed.)

## Cache-coherency check

The "output empty" reading assumes the CPU read reflects DRAM. rocket_gem's dual-path
`prep_bo` check was broken — `memremap(…, MEMREMAP_WC)` returns NULL on RAM, so the
`wc=deadbeef` column is just the NULL marker; it never cross-checked DRAM. The NPU is
non-coherent and the vendor uses an explicit `dcache_inval_poc`, rocket uses
`dma_sync_sgtable_for_cpu` — a real difference worth verifying.

Added an explicit `dcache_inval_poc` + re-read (patch `0027`). Filling the output BO
with `0xAA` before the job:

```
prep_bo:       iova=0xfff57000 cached=aaaaaaaa aaaaaaaa aaaaaaaa aaaaaaaa
prep_bo INVAL: iova=0xfff57000 forced=aaaaaaaa aaaaaaaa aaaaaaaa aaaaaaaa
```

`cached == forced` for every BO (weights `f8a700d3…`, input `83828180…`, output
`aa…`) → `dma_sync` was invalidating correctly, and the output BO genuinely holds the
`0xAA` fill. **The DPU wrote nothing to the final output; the wall is real, not a
cache-read artifact.**

## Driver submit-registers — values and order

The env/writel diffs above are unordered set diffs. wtrace also logs the value, so the
driver's own per-submit register writes (not the mesa/replay regcmd payload) can be
compared value-for-value:

| reg | vendor | rocket |
|---|---|---|
| `0x10` state_init | `1` | `1` |
| `0x1004` toggle | `0 / 1 / 0x1e / 0xe` | `0 / 1 / 0x1e / 0xe` |
| `0x3004` | `0xe` | `0xe` |
| `0x20` INT_MASK | `0x300` | `0x300` |
| `0x24` INT_CLEAR | `0x300` / `0x1ffff` | `0x30000300` / `0x3001ffff` |
| `0x30` TASK_CON | `0x00070050` | `0x00070001` |
| `0x34` | `0` | `0` |
| `0x8` OP_EN | `1` → `0` | `1` → `0` |

Values and order match, with two benign differences: rocket clears extra INT bits
(`0x30000000`, PC_DONE) at `0x24` — rocket does *more*, not less; and `0x30` differs
only in the task count `N` (`0x50` vs `0x1`, the two runs' workloads). The
iterate-enable `0x7<<16` in TASK_CON is written by both, and the PC demonstrably walks
all tasks in the replay (per-task engage, buf[1..4]), so the earlier TASK_CON
"didn't latch" confound does not hold here — the wall is *after* task iteration
(tasks run; the final CMAC output never lands).

## Where this leaves it

On this stack the software surface checked so far — regmap env, direct writel
(incl. IOMMU), the read-based pd-arm, per-submit TLB flush (really done), CPU cache
coherency, and the driver's submit-register values + order — is negative: no
register, value, or maintenance op the vendor does that rocket doesn't accounts for
the wall. This **hardens** the "arm is below software (RTL / internal sequencer
state)" reading each time a candidate falls, but does not by itself prove it. The
regcmd payload's own values are identical by construction (`replay_rocket` replays
the vendor-captured bytes). Not checked: barrier/fence timing (low-probability).

## Repro

Build the dual image (vendor rknpu + rocket on one 7.1.3 kernel, two DTB variants);
boot the `rocket` entry. Patches `0025`-`0027` add the fix + the two probes.
`rocket.wtrace=1` + `capture/wtrace-diff.py` do the writel diff; `replay_rocket` with
an `0xAA`-filled output BO + `prep_bo INVAL` do the cache check.
