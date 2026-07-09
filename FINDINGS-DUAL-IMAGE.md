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

## Where this leaves it

On this stack the software surface checked so far — regmap env, direct writel
(incl. IOMMU), the read-based pd-arm, per-submit TLB flush (really done), and CPU
cache coherency — is negative: no register or maintenance op the vendor does that
rocket doesn't accounts for the wall. This **hardens** the "arm is below software
(RTL / internal sequencer state)" reading each time a candidate falls, but does not
by itself prove it. Not yet checked: an ordered/valued register diff (env + wtrace
were unordered set diffs, and the two stacks run different workloads), and
barrier/fence timing.

## Repro

Build the dual image (vendor rknpu + rocket on one 7.1.3 kernel, two DTB variants);
boot the `rocket` entry. Patches `0025`-`0027` add the fix + the two probes.
`rocket.wtrace=1` + `capture/wtrace-diff.py` do the writel diff; `replay_rocket` with
an `0xAA`-filled output BO + `prep_bo INVAL` do the cache check.
