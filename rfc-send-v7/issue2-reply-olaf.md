Hi Olaf, thank you for going back into the BSP for this. Two of your four
points landed, and one of them landed on something I had already got wrong in
public, so let me answer all four straight.

**The wall is solved, and it was neither of our theories.** 2026-08-07. It is
one register write. `PC_TASK_CON` packs the task number, and rocket's
`rocket_registers.h` is derived from RK3588, where that field is 12 bits wide
with `TASK_PP_EN` and `TASK_COUNT_CLEAR` above it. RK3576 uses a **16 bit**
task number:

```
rocket, v1 through v6:  TASK_CON = 0x00007001
vendor driver, RK3576:  TASK_CON = 0x00070001
```

So the PC read our word as `task_number = 0x7001`, that is 28673 tasks, with
the count clear landing on nothing. Found by taking an ordered trace of every
register write during one submit and diffing it against the same trace from the
vendor driver on the same board: exactly one value differed.

Your "only a full reset clears it" reading was right about the symptom and it
is worth saying why: a reset was the only thing that ever cleared the counter,
because the bit meant to clear it was landing on a reserved bit. You read that
as `state_init` being the only thing that re-arms. Same observation, and the
counter explanation is the one that survives.

Chaoyi Chen from Rockchip
[confirmed the layout on the list](https://lore.kernel.org/all/4f300b78-d96d-4d98-8819-dc292b0c9b97@rock-chips.com/)
on 2026-08-10, including a fourth control at bit 18, `task_last_layer_clear`,
that neither the trace nor I knew existed:

```
RK3588   BIT[11:0] task_number  BIT[12] task_pp_en  BIT[13] task_count_clear
RK3576   BIT[15:0] task_number  BIT[16] task_pp_en  BIT[17] task_count_clear
         BIT[18] task_last_layer_clear
```

**Your point 2 is correct, and I had it wrong in six cover letters.** The job
interrupt block is at `0x20`/`0x24`/`0x28`, not at `0x1024`, and rocket already
uses it: `REG_PC_INTERRUPT_MASK` is `0x20` in its own header, and the submit
path writes `INT_MASK` and `INT_CLEAR` per job. So "bit 31 of INTERRUPT_MASK"
was never the job mask, exactly as you say. The completion interrupt does reach
the GIC on RK3576. It never fired because the PC believed it had 28672 tasks
left. With the fix and the poll disabled, so only a real interrupt can retire a
job, a convolution runs three times out of three with zero timeouts and
`/proc/interrupts` counting up.
[Correction sent to the list](https://lore.kernel.org/all/20260807211629.1573228-1-gahing@gahingwoo.com/);
v7 drops the poll entirely.

**On the clock, point 3: it was not a GPLL sweep.** Sorry, the write up must
have been unclear. What was done was a same-kernel clock diff, vendor against
rocket, which came back `aclk` 786 MHz for rocket and 594 for the vendor, and
then rocket was forced to exactly 594. The multi task behaviour did not change.
The read margin write was tried on the board separately and was also null. So
the rate is excluded with hardware data rather than by a sweep of the wrong
domain, and with the counter explanation above there is nothing left for it to
explain.

**Point 4 is the useful one and I am taking it.** SRST plus
`iommu_detach_device` and `iommu_attach_device`, rather than cycling the power
domain, is what the fork's reset path does now, and the `failed to set idle on
domain 'nputop'` wedge does not appear with it. Your reading that the vendor
simply never power cycles mid session matches what the reset path does.

Since you have the BSP open, one thing that would help. `rknpu_fuzz_status()`
masks the status before comparing it against the compiled `last_task->int_mask`.
If you can paste what it masks off, that would settle whether a multi task job
can raise a status that the vendor deliberately ignores.

**Where it stands now.** Every regular convolution shape computes, byte exact
per output channel: 5x5, 3x3 and 1x1, stride 1 and 2, 16 and 128 output
channels. Depthwise computes too, since yesterday: a 112 wide layer is
dispatched as row windows, each window overlaps the one before it by a row, and
the driver was staging those overlap rows a second time, so everything after
them sat two rows late and the window convolved shifted input. The vendor's
capture writes two different row counts there where the driver wrote one.

Still open: a depthwise at 1024 channels, chained operations, and MobileNet,
which has both. Full ledger in FINDINGS.md.
