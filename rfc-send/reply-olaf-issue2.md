Answering your NPU1 question, and what came out of chasing it.

**Does rocket arm both npu0 and npu1?** Yes, and it has since 2026-06-19 —
`rk3576-rock-4d.dts:881` lists both domains on `rknn_core_0`, and
`rocket_core.c:139` calls `devm_pm_domain_attach_list()` explicitly (a multi-PD
device skips the driver-core single-PD auto-attach). Our board is a ROCK 4D, so
every experiment since then already ran with both up. Wall unchanged.

So that's a clean negative for the genpd theory, which is the result you said
would also be useful. Sorry it isn't the other one.

**But your dump did lead somewhere.** Alexey Charkov asked on the kernel list
whether the vendor also polls for completion instead of using the interrupt. It
doesn't — vendor rknpu on RK3576 requests `npu0_irq`/`npu1_irq` on the same GIC
lines we use and waits on a completion. So I probed our interrupt path, and found
this:

- Per power session the GIC line fires **exactly once**, on the one op that
  computes: `raw=0x30000155` = `DPU_0|CORE_0|CNA_CSC_0|CNA_WEIGHT_0|CNA_FEATURE_0`.
- `INTERRUPT_MASK` bit 31 is set by hardware at that interrupt. While it's set the
  line never fires again. No register write clears it (swept `INTERRUPT_CLEAR`
  0x1ffff/0x80000000/0xffffffff and `INTERRUPT_MASK` 0x80000000/0/0x300).
- A **full NPU reset** clears it. With a reset before every op, in one power
  session with no power cycling: **90 ops, 90 resets, 87 interrupts**, against one
  before.

And the data path comes back with it — per-layer input and weight fetch at the
graph's real shapes, and DPU write-back:

```
wt_rd in {96, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}
dt_rd in {1568, 3136, 4704, 6272, 9408, 12544, 25088}
core dt_wr nonzero on ~56 of the 90 ops
```

What's still dead is the multiply-accumulate — the DPU writes out a zero-point
surface (output `distinct=1..10`). So the wall isn't "the pipeline only arms once
per power session" like we thought; arm, input DMA, weight DMA and write-back all
work, and the MAC produces nothing.

**One thing that might interest you specifically**, since you have a working
vendor BSP and have been reading genpd: after 90 mid-session resets the NPU power
domain can't be shut down, and it takes the system with it.

```
npu0 -> OFF
rockchip-pm-domain: failed to set idle on domain 'nputop', val=0
cpu4: _set_opp_voltage: failed to set voltage (712500 ...): -110
cpufreq: __target_index: Failed to change cpu frequency: -110
rcu: INFO: rcu_preempt detected stalls on CPUs/tasks   -> CPU0 wedged
```

Something is left outstanding on the NPU's AXI/BIU, `nputop` never reaches idle,
and it propagates into the shared regulator/I2C path. If the vendor stack does a
drain/quiesce before power-off that we're missing, that would be worth knowing —
it's genpd-adjacent and right where you've been looking.

Full write-up is in FINDINGS.md (top entries). Thanks again for the dump and for
the clock lead before it — both came back negative for the wall, but both moved
the search.
