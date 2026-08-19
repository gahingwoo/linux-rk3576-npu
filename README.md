# linux-rk3576-npu

Mainline kernel bring-up for the RK3576 NPU on Radxa ROCK 4D.

MobileNet V1 runs end to end on the NPU and **returns the right label**: on the
test image it picks class 754, the class the CPU reference picks, with the CPU's
top five in the same order. Every one of its layers, run on its own, is **99.93
to 99.99 percent of pixels identical to exact integer arithmetic**, which is
closer than the tflite interpreter most of the numbers here are scored against. An open LLM runtime computes a signed int8 matmul through this driver
**byte exact**, at 11.9 GB/s of weight bandwidth. Details below.

## Companion projects

Three repositories, one board. The third name is a joke about the second: char siu
is Cantonese barbecue pork, eaten across Guangdong, Hong Kong and Malaysia, and a kiln is the
oven it is roasted in.

| repo | what it is |
|---|---|
| **linux-rk3576-npu** | this one: the open RK3576 NPU driver and Mesa work. `rocket` on the list, Teflon in Mesa, and the register knowledge the other two are built on |
| [kiln](https://github.com/gahingwoo/kiln) | the **vendor** RKLLM/RKNN stack on a mainline kernel. LLM and vision on the board today, through a closed runtime, and the yardstick the open stack is measured against |
| [charsiu](https://github.com/gahingwoo/charsiu) | an open **LLM** runtime for this NPU on the open driver. It reaches the NPU through `rocket` on its own and computes a signed int8 matmul byte exact, with no Mesa and no vendor runtime in the path |

## Upstream

The driver support is on the list. Current series:

**[PATCH v8 0/12: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/20260817113603.1436067-1-gahing@gahingwoo.com/)**
(2026-08-17, on top of Igor Paunovic's clocks-by-name fix)

No patch of the twelve has been applied anywhere. It carries a Reviewed-by from
Krzysztof Kozlowski on the binding and one from Igor Paunovic on the refactor
that arrived an hour after posting.

The testing is his and it is worth reading rather than counting. On 19 August he
re-ran v8 on three RK3588 cores against a **differential base**, the same tree
and config with 1/12 and 2/12 not applied, two passes each at two log levels,
and reported 12 and 8 induced resets against 12 and 13, all clean, with his
oracle at 48 of 48 on both kernels. His v7 tag carries to the v8 shape of 1/12
as re-run; 2/12 has a fresh one naming exactly what was tested. He also said
what the protocol cannot say, that the race itself never manifested in 45
resets and the justification for the pair remains the source analysis.

v9 exists and is held, to let v8 collect more review rather than reset the
thread. Its 2/13 folds in an interrupt mask he raised, so it is not the patch he
tested and his tag is deliberately not carried across.

Earlier revisions:
[v1](https://lore.kernel.org/all/20260717085220.3212274-1-gahing@gahingwoo.com/) |
[v2](https://lore.kernel.org/all/20260718031146.3368811-1-gahing@gahingwoo.com/) |
[v3](https://lore.kernel.org/all/20260731043507.1832277-1-gahing@gahingwoo.com/) |
[v4](https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/) |
[v5](https://lore.kernel.org/all/20260805063826.95682-1-gahing@gahingwoo.com/) |
[v6](https://lore.kernel.org/all/20260806063413.350184-1-gahing@gahingwoo.com/) |
[v7](https://lore.kernel.org/all/20260812094106.1391698-1-gahing@gahingwoo.com/)

v7 is the first revision sent as PATCH rather than RFC, because the thing every
earlier cover letter described as unsolved is solved and Rockchip has confirmed
the register layout behind it.

It opens by withdrawing a claim carried from v1 to v6: that the RK3576's
completion interrupt never reaches the GIC. It does. It never fired because the
block believed it had 28672 tasks left to run. So v7 removes the polled
completion path entirely, writes `PC_TASK_CON` with the RK3576 field layout,
splits the `job_lock` fix into its own patch with a Fixes tag, attaches the
power domain list before `iommu_group_get()` so a failure needs no unwinding,
and grows `struct rocket_core`'s `clks[]` in the patch that adds the names
rather than the one that claims to change nothing for RK3588. The last two are
Igor Paunovic's review of v6.

The v8 branch was run on the board before it was sent, with none of this
repository's out of tree patches applied, including no `rk_iommu`
`flush_iotlb_all`: three submits with three different inputs match the CPU
reference within one count on every channel each time, the NPU's interrupt count
goes from zero to three across them, and probe, unbind and rebind are clean with
no warning.

That is not byte exact and an earlier version of this file said it was. Counted
strictly the three runs are 204788, 204760 and 204767 identical pixels of
204800, so 12 to 40 pixels differ by one. Nothing here printed the strict count
until 2026-08-17. The same input either side of the rebind reproduces its count
exactly.

Reviewers so far: Chaoyi Chen, Krzysztof Kozlowski, Alexey Charkov, Heiko
Stuebner, Tomeu Vizoso, Philipp Zabel, Robin Murphy, Diederik de Haas and Igor
Paunovic, who provides the RK3588 coverage this project cannot produce.

Two iommu patches from the same work are already merged, in linux-next since
next-20260727: `841363ebb508` ("iommu/rockchip: Take all DT clocks") and
`b10d5920cafa` ("iommu/rockchip: Clear stale page faults before enabling
stall").

## The reference is the inaccurate one, measured on the board this time (2026-08-19)

⚠ **This section re-establishes something rounds 99 to 101 had already settled**,
and `vendor-capture/chainmodel.py` has printed since 13 August. Its own
docstring says the pervasive one sided off by one is tflite's double rounding
and not the hardware, and that by operator 8 a perfectly correct accelerator
would score 34 of 256 channels against the CPU. Six board rounds went into
rediscovering that. The two numbers below, 4 of 128 at operator 6 and 34 of 256
at operator 8, are the ones that file predicted. What is new here is the per
operator measurement on hardware rather than the prediction, and it agrees.

Its requant is a `SaturatingRoundingDoublingHighMul` followed by a
`RoundingDivideByPOT`, which rounds a half away from zero. Computed against
exact integer arithmetic, with one rounding at the end and nothing
approximated, it reads high on 14.41 percent of a MobileNet depthwise's pixels.
The board measured this driver differing from the interpreter on 14.38 percent
of the same pixels, every one of them the other way.

| layer | vs the interpreter | **vs exact arithmetic** | the interpreter's own error |
|---|---|---|---|
| `mn_dw1` | 85.62% | **99.98%** | 14.41%, all high |
| `mn_pw2` | 99.22% | **99.93%** | 0.86%, all high |
| `mn_pw24` | 99.81% | **99.99%** | 0.18%, all high |
| `mn_conv0` | 99.80% | **99.98%** | 0.22%, all high |
| `mn_dw25` | 99.29% | **99.98%** | 0.70%, all high |
| `conv2d-cal` | 99.81% | 99.80% | 0.03%, both ways |

That depthwise's multiplier is 0.292, so its final divide is by two and one
pixel in seven lands on a tie the interpreter rounds up. `conv2d-cal` is the
control: the interpreter barely deviates there, this driver does by 0.03
percent, and scoring it against exact arithmetic changes nothing. Had the new
reference simply agreed with everything, that row would have moved too.

**The `85.62%` that sat in this file for weeks was never a driver problem**, and
the file already said as much elsewhere.

⚠ This makes a whole class of knob a trap. `ROCKET_ABIAS=1` takes that
depthwise from 85.62 to 98.88 percent agreement with the interpreter and from
99.98 down to 84.47 percent against exact arithmetic. It takes `mn_pw24` to
byte exact against the interpreter and away from exact. Chasing agreement with
the reference is chasing its rounding.

The chain degradation this file used to describe follows from the same thing.
Every operator run in isolation is within one count with all its misses one
sided, a two operator model and the full 31 operator graph read at the same
tensor agree in every column, and what accumulates with depth is the
reference's rounding rather than the hardware's error.

`rootfs-overlay/opt/npu-test/exactref.py` computes the exact reference for a
single convolution and `perch.py` prints it alongside, which is the on board
per operator half of what `chainmodel.py` predicts offline for a whole graph.

## The output stage floors at zero, and the fix is one constant (2026-08-19)

Every convolution here whose output zero point is not zero came back with its
whole lower half pinned at that zero point, as if a ReLU sat on the
accumulator. It scored 128 of 128 anyway, because the reference it was scored
against was `max(cpu, out_zp)` and both surfaces were flattened the same way.
Against the raw CPU output it was 0 of 128.

The output stage is

    byte = clamp(max(requant + L, 0) + offset, -128, 127) + 128

with the floor applied BEFORE the offset, so a negative requant is gone before
the offset can do anything about it. A byte of `clamp(requant + out_zp, 0, 255)`,
which is what the operation means, needs `L + offset == out_zp - 128` and needs
`L >= 128` so the floor never bites. This driver shipped `L = 0` with
`offset = out_zp - 0x80`: the sum is satisfied and the floor bites. `L = 128`
with the offset 128 lower is the pair that does not.

| model | out_zp | vs raw CPU before | after |
|---|---|---|---|
| `conv2d-cal` | 128 | 0 / 128 | **128 / 128** |
| `cal_k3` | 128 | 0 / 128 | **128 / 128** |
| `cal_oc16` | 128 | 0 / 16 | **16 / 16** |
| `pw33x64w56` | 0 | 64 / 64 | 64 / 64, byte for byte |

`L = 129` and `L = 160` give the same result as `L = 128`, because the offset
cancels whichever lift is used and only the inequality does any work. The
constant is not fitted, which is more than can be said for several earlier ones
in this file.

It is the hardware and not this driver, and an earlier version of the Mesa merge
request said the opposite. The vendor userspace on the same board does not clamp
because it lifts too. charsiu found the same floor independently on the same
silicon, with a control that separates a floor at zero from a rail at -128, and
has carried the lift since its own round 163; porting the constant without
porting the reason cost one board round, because charsiu's output zero point is
zero and its offset was already -128, so the compensation came free there.

⚠ Every accuracy figure in this file dated before this one, on a model whose
output zero point is not zero, was scored against `max(cpu, out_zp)`. Of the
133 models in the regression set, 31 have at least one operator with a nonzero
output zero point and are in that class.

An earlier version of this section said MobileNet was not among them because
every layer in it has an output zero point of zero. That is wrong. Its final
classifier convolution, a 1x1 over 1024 channels to 1001, has an output zero
point of 66, and the floor pinned every logit below it. What survives is the
`1000 of 1001` figure itself, which is measured on the softmax output, and that
tensor's zero point is zero, so the old reference was not hiding anything at
the point of measurement. What does not survive is the assumption that nothing
upstream of it moved. The label is still right for a reason that does not
depend on the floor, since the top logit is far above 66, but the numbers
between here and there have not been re-measured yet.

## An LLM runtime computes on this driver, and it has been timed (2026-08-15)

[charsiu](https://github.com/gahingwoo/charsiu) submits its own register streams
through `rocket` and gets answers back: no Mesa, no Teflon, no vendor runtime. Its
matmul is **byte exact** against a CPU reference, not close to it, including at
M = 1 with K = 512 and N = 1024, which is a projection's own shape.

**What that measures about this driver.** A submit carries jobs and a job carries
tasks; tasks in one job are chained on a single core with no further ioctl, which
is the path the `PC_TASK_CON` fix in v7 opened. Sweeping seven shapes at 32
chained tasks and fitting them together:

```
us per task = 26.3 + weight_MB * 84.3        i.e. 11.9 GB/s, plus 26 us per task
```

with a further **172 us of fixed cost per submit** that chaining removes. Two
pairs of shapes with the same weight bytes but different geometry came out 0.3%
and 1.5% apart, and M = 32 costs 1.08 times M = 1 for 32 times the arithmetic, so
the cost is the weight fetch and neither the MAC nor the dispatch. Two jobs of
eight tasks were about 5% worse than one job of sixteen, which is what a
bandwidth bound workload does with a second core.

**A weight layout can be asked rather than inferred.** Put one live weight in the
whole buffer, sweep it, and record which output channel lights. Run against int8,
which is byte exact through this driver, all 512 probes of a 64 by 64 buffer light
exactly one channel with `n = byte / 32` and `k = byte % 32`, which is what the Mesa
packer writes. So the int8 weight layout is no longer only inferred from correct
outputs: the hardware was asked and it agrees. The same probe on int4 found the
activation element to be two bytes wide, and, once the vendor's `w4a16` output stage
was ported, that this NPU writes a 4 byte **integer** accumulator on that path rather
than a requantised byte, with weight byte `b` feeding output slot `b / 8`. All of that
is in [charsiu](https://github.com/gahingwoo/charsiu).

**And a job can leave this NPU unable to start the next one.** charsiu's `w4a16`
stream, int4 weights against fp16 activations, completes and writes its output, and
then the next int8 job on the same device times out with its output untouched and
`rk_iommu: Error during raw reset` beside it. The same int8 binary and the same
register stream is byte exact when it runs first, and its stream is byte identical
before and after the w4a16 work, so it is not the int8 side that changed. Mesa's own
models run correctly afterwards, so `rocket` does recover. Which registers do it is not
localised yet, and it is recorded here rather than only in charsiu because if it turns
out to be state the driver should be clearing between jobs, it is this driver's bug.

Two other things charsiu found are the driver's business too. **The vendor's
`.rkllm` files carry their register command streams**, exactly as `.rknn` files
do, so what the closed LLM stack asks this NPU to do can be read offline; that is
how the projections were found to be dispatched at one row per submit, split
across the two cores, and how its attention was found to be precompiled into
exactly 128 KV buckets from 32 to 4096 in steps of 32. And **`0x102c` and
`0x1078` carry the width minus one in their high half, not the row count** - every
convolution those were read from was square, so the two readings were the same
number. Nothing here is wrong because of it, since every shape this driver runs
is square, but a non square input would be.

## Every shape in the regression set computes (2026-08-16)

`pw64x56w56`, a 1x1 convolution with 56 output channels, had timed out in every
round it was ever run. It now comes back **56 of 56, every channel correct**,
with the old behaviour reproducible in the same log through
`ROCKET_DPU4050_MOD32=1`.

**`0x4050` follows the parity of `DIV_ROUND_UP(oc, 16)`, not `oc % 32`.** The
modulo rule was fitted honestly, on ten vendor models compiled at 16 to 160
output channels in steps of 16, 10 for 10. But every one of those counts is a
multiple of 16, and on that set the two predicates are the same predicate. They
differ only where `oc mod 32` falls between 17 and 31, and 56 is such a count:
`DIV_ROUND_UP(56,16)` is 4, so the parity form asks for `0x80011111`.

Three counts have been run, and they are one data point rather than three:

| oc | parity form | modulo form |
|---|---|---|
| 56 | 56 of 56 | 32 of 56, times out |
| 88 | 88 of 88 | 64 of 88, times out |
| 120 | 120 of 120 | 96 of 120, times out |

56, 88 and 120 are all 24 modulo 32, so the twenty four channels each loses are
forced by the arithmetic and are not corroboration. **20, 50, 60, 90 and 114
discriminate and nobody has run them on either SoC.** 40 and 72 do not, and an
earlier version of this file and a mail to the list both said they did.

⚠ Five fields of the value itself are still unexplained. Against `registers.xml`
this driver's `0x80011111` differs from upstream's `0x124` in `RGP_CNTER` 8,
`RESERVED_0` 34, `SIZE_E_1` 0, `SIZE_E_0` 4 and `OW_SRC` 1, all of which came
from vendor captures and none of which has been varied one at a time. Only
`SIZE_E_2` has a reason behind it. That sweep was promised before the Mesa
series went out and the series went out first.

**How it was found is worth more than the fix.** charsiu drives this same
hardware through the same driver with its own register streams, and it computes
the identical arithmetic, 64 input and 56 output channels over 3136 rows, to
200344 of 200704. So the hardware was never the limit. `ROCKET_PW_RESHAPE`
then re-expressed this driver's 1x1 surface as N columns until its geometry
matched charsiu's exactly, and with that matched the diff between the two
streams collapsed to six addresses, three requant registers and **one**
remaining difference, which was `0x4050`.

What that ruled out on the way, each with a control that could have failed: the
register stream itself, the output buffer, the input CBUF budget at six
settings, rounding the output count to the feature atom, and the spatial axis.

## Any input channel count computes (2026-08-16)

A 1x1 convolution with **33 input channels** went from 18 of 64 channels correct
to **64 of 64, every channel correct**. The old reading of this fault, carried
since round 176, was "input channels above 32"; that was wrong, because a 64
channel pointwise was always right. It is ic not being a multiple of **16, the
feature atom**. charsiu settled that without a Mesa build at all: a matmul is a
1x1 convolution, so its K is this ic, and sweeping K gives byte exact at 16, 32,
48, 64 and 96 and wrong at 31, 33, 40, 63 and 65. **40 is a multiple of 8 and
fails; 48 passes**, so the boundary is neither 8 nor 32.

Three separate places counted the real channel count and all three had to move:

| | what |
|---|---|
| the weight buffer | laid out to `ALIGN(ic, 16)`. The INPUT side already padded, `task->input_channels`, so the buffer was **shorter than the byte count the CNA had been given** |
| five CNA registers | `0x101c`, `0x1020`, `0x1028` low, `0x1030` high, `0x107c`, all from one `ic = task->input_channels_real`. Found by dumping this driver's own stream with `ROCKET_DEBUG=dump_bos` and diffing it against charsiu's for the same arithmetic |
| `calculate_weight_sum()` | the padded channels are in the **hardware's** sum, so they belong in `sw`. Each padded weight is `w_q = 0x80` and contributes `(0x80 - wt_zp)`; since `A = bias - (in_zp - 0x80) * sw`, a short sum lands as one constant on every pixel of the channel |

Measured after each: slope 0.44 to 0.98, then the per channel offset's standard
deviation 69.11 to 0.85, then correct. The last term is derived rather than
fitted, and it is identically zero when ic is already a multiple of 16, which is
why `pw64x41w56` and `conv2d-cal` are the control and never moved.

**This does not change MobileNet V1**, whose channel counts are 32, 64, 128 and
so on, all multiples of 16, so the term is zero throughout it. The shape above
is a synthetic one built to isolate the fault.

## MobileNet V1 runs end to end (2026-08-13)

The whole network now produces a real classification on the NPU with the open
stack: **1000 of its 1001 outputs land within one count of the CPU reference**,
with the same ten distinct values the CPU produces. Every run before this one was
1001 channels of zero. The figure was 995 when this section was written; the odd
output channel count that the CNA reads in pairs accounted for the other five.
The per layer table below is from the 995 run and has not been retaken, because
what it is there to show is the comparison against a perfect accelerator rather
than the final vector.

Layer by layer, against `vendor-capture/chainmodel.py`, which runs the graph
twice from the model file, once with tflite's requant and once with the
hardware's, and so says what a **perfect** accelerator would score:

| operator | kind | board | correct hardware scores |
|---|---|---|---|
| 3 | depthwise | 21/64 maxdiff 13 | 21/64 maxdiff 13 |
| 4 | 1x1 | 18/128 maxdiff 14 | 18/128 maxdiff 14 |
| 5 | depthwise | 9/128 maxdiff 13 | 9/128 maxdiff 13 |
| 6 | 1x1 | 4/128 maxdiff 23 | 4/128 maxdiff 23 |
| 7 | depthwise | 7/128 maxdiff 10 | 7/128 maxdiff 10 |
| 8 | 1x1 | 34/256 maxdiff 7 | 36/256 maxdiff 7 |
| 24 | 1x1 | 653/1024 maxdiff 5 | 671/1024 maxdiff 6 |
| 26 | 1x1 | 574/1024 maxdiff 28 | 572/1024 maxdiff 25 |

Operators 3 to 7 are exact, and past that the two agree within a few channels
in **both** directions, the board reading better than the model at 12 and at
26. A low channel count deep in the network is the reference's own compounding
rounding, not a defect, and without that column it cannot be told from one.

Four faults stood between the working single operators and this, all in Mesa
and none in the kernel:

- the **1x1 weight buffer is 32x32 tiles in both axes**, `[oc/32][ic/32][oc%32]
  [ic%32]`. Every layout used before agrees with that whenever `oc` or `ic` is
  32 or less, which is every shape it had ever been checked at, because a probe
  that gives each `(oc, ic)` pair its own byte caps at 255 positions. Two models
  of one shape, one whose weight depends only on the output channel and one
  only on the input channel, lift that cap and name both coordinates of every
  byte.
- **a row whose last CBUF unit would hold exactly three atomics does not pack**
  and costs a whole unit per column. `rkt_task.c` always knew; `rkt_regcmd.c`
  divided instead. They agree unless the atomic count is 3 modulo 4, which is
  33 to 48 input channels and 113 to 128.
- **the CBUF split pair is the window count, not the stride.** Reading `0x1018`
  out of 87 compiled `.rknn` and comparing each with its own window count, the
  pair says "more than one row window" in 86 of them.
- **the coefficient buffer's second operand has to be 16 byte aligned.** It sat
  at `table_bytes + oc * 2`, and the table in front is always a multiple of 64,
  so the address was aligned exactly when the output channel count was a
  multiple of 8 and odd when the count was odd. Every layer that missed came
  back an **empty convolution**, which is why MobileNet's last operator, 1024 to
  1001, produced nothing at all.

A fifth followed on 2026-08-14: **the CNA counts output channels in pairs.** At 41
output channels the vendor emits weights for 42 and writes 41 in `0x1024`, while
its CORE, DPU and RDMA all still carry 40. Rounding the count up there, and laying
the weight tiles out to match, took every odd output channel count from wrong
across its whole second tile to exact, and MobileNet from 995 of 1001 to
**1000 of 1001**.

Still open, both in Mesa: a pointwise with **56** output channels times the NPU
out, and **33** input channels is wrong for a reason the packed row cost did not
cover.

## Every regular convolution shape computes, and so does depthwise

Bring-up works: the NPU probes, powers up and down through runtime PM, and runs
jobs to completion. Submits recompute, and the completion interrupt arrives.

**Fixed since 2026-08-07.** The block used to accept exactly one task per reset,
which made every later submit a no op that never wrote its output, so userspace
read back whatever was in the buffer already. The cause was one register write.
`PC_TASK_CON` packs the task number, and `rocket_registers.h` is derived from
RK3588 where that field is 12 bits wide, with `TASK_PP_EN`, `TASK_COUNT_CLEAR`
and `RESERVED_0` above it. RK3576 uses a **16 bit** task number, so those three
controls sit at bits 16, 17 and 18:

| | value written to `0x0030` |
|---|---|
| rocket, v1 through v6 | `0x00007001` |
| vendor driver on RK3576 | `0x00070001` |

The PC read our word as `task_number = 0x7001`, that is 28673 tasks, with the
count clear landing on nothing, so only a reset ever cleared the counter. Found
by taking an ordered trace of every register write during one submit and diffing
it against the same trace from the vendor driver on the same board: exactly one
value differed.

**Confirmed by Rockchip.** On 2026-08-10 Chaoyi Chen replied on the list with
the field layout from the vendor side, which matches what the trace had already
forced:

```
RK3588   BIT[11:0] task_number  BIT[12] task_pp_en  BIT[13] task_count_clear
RK3576   BIT[15:0] task_number  BIT[16] task_pp_en  BIT[17] task_count_clear
         BIT[18] task_last_layer_clear
```

RK3576 also has a fourth control at bit 18 that this work did not know about.

**That also corrects a claim carried in all six cover letters.** The completion
interrupt does reach the GIC on RK3576. It never fired because the PC believed
it had 28672 tasks left. With the fix and the poll disabled, so only a real
interrupt can retire a job, a convolution runs three times out of three with
zero timeouts. [Correction sent to the
list](https://lore.kernel.org/all/20260807211629.1573228-1-gahing@gahingwoo.com/),
and v7 removes the poll.

**What computes today**, every one confirmed per output channel against the
CPU, in a single boot, with a control model passing at both ends of the run:

| convolution | output channels correct |
|---|---|
| 5x5 stride 2, 16 in, 128 out | 128 / 128 |
| 5x5 stride 1, 16 in, 128 out | 128 / 128 |
| **3x3**, 16 in, 128 out | **128 / 128** |
| **1x1**, 16 in, 128 out | **128 / 128** |
| 5x5 stride 2, 16 in, 16 out | 16 / 16 |
| input zero point 0 | 128 / 128 |
| pointwise from MobileNet, 32 in, 64 out | 64 / 64 |

Two of those came from earlier Mesa fixes, where a register had been filled from
a constant fitted to one capture rather than derived:

- `CNA 0x1080` is the **padding** register,
  `(pad_right << 24) | (pad_bottom << 16) | (pad_left << 8) | pad_top`. The
  constant it replaced, `0x02020101`, is exactly SAME padding for a 5x5 stride 2
  convolution, so every other geometry was configured with the wrong padding.
- `DPU 0x4050` depends on the **output channel count**: `0x80011111` for a
  multiple of 32 and `0x80011011` otherwise, ten for ten across a sweep.

Both were found by compiling vendor `.rknn` files on the host at chosen
geometries and reading the registers back, which the RKNN toolkit supports from
ONNX on arm64. That turns "what does the vendor put here" into a question
answerable without the board, and it is how most of what follows was settled
too.

**The kernel size was never the dividing line.** For months 3x3 and 1x1 were
carried as two separate hardware mysteries, each with its own theory. Both were
the same bug, and it was in this driver's Mesa side.

`rkt_coefs.c` filled a region of the coefficient buffer with a float32
dequantised weight per weight, `MAX2(ic*oc*k*k, 8192)` of them, 197888 bytes for
the model that worked. Measured on hardware per output channel, keeping the
first **four** bytes of that region and zeroing the rest leaves every channel
correct, and keeping zero bytes leaves none. So one word out of 197888 bytes was
doing the work.

That word is not read as a float at all. Flipping its sign changes nothing.
Doubling it changes nothing. Clearing its low byte, worth 0.0005 as a float,
destroys all 128 output channels. Twenty four words later the requirement is

```
(w & 0x3f) == 0x04    and    ((w >> 6) & 0xff) >= T,   0x21 < T <= 0x3f
```

a bitfield in the low 16 bits, with bits 14, 15 and everything above them free.
The old code was filling it with a dequantised weight, so **whether a model
computed came down to whether its first weight happened to carry the right
bits.** The 5x5 model's did and the 3x3 model's did not.

Mesa now writes one constant there, `0x1004`, and the 197888 byte surface is
gone. The rule was tested as a prediction before it was believed: `0x1004` is
the smallest word it allows and had never been run, `0x3fc4` sets every free bit
at once, and both pass while the near misses beside them fail.

This also explains a negative result that had been puzzling: compiling vendor
`.rknn` files on the host and comparing them shows the vendor's coefficient
buffer carries **no kernel size dependence at all**. There was none to find.

## Depthwise: three bugs, all closed

Fixed 2026-08-11. Every depthwise layer tested is now correct on every output
channel, at both channel counts this project has models for:

| model | before | after |
|---|---|---|
| MobileNet dw1, 112x112, 32 channels | 9 / 32, of which 1 real | **32 / 32** |
| MobileNet dw25, 7x7, 1024 channels | 432 / 1024, of which 2 real | **1024 / 1024** |
| impulse models at both sizes | 0 | **all channels** |

Three separate faults were behind it, each with a control that reproduces it.

**The coefficient record.** A depthwise uses a 48 byte record, `[A 8 x int32]
[C 8 x int16]` with no B, and twice as many records as a regular conv, with the
per-channel fp16 weight scale after them. This driver wrote the regular conv's
64 byte record. The table is not in the `.rknn` at all, which is why earlier
searches of the model file concluded there was none: librknnrt builds it at
load time, and resolving a runtime capture's address registers back into the
captured buffers finds it immediately. Both `A` and `C` then reproduce from the
model with nothing fitted, for all 32 channels of a depthwise and a regular
layer that differ only in `groups`.

**The row window staging.** A 112 wide layer does not fit in the CBUF at once,
so it is dispatched as row windows, 90 output rows then 22. Each window
overlaps the one before it by a row on each side, and those rows are already
staged; the reuse base at `CNA 0x103c` points back at them and this driver
computed it correctly. `rkt_split_tasks` then staged them **again**, so every
row after the overlap sat two rows late and the window convolved shifted input.
The vendor writes two different row counts there where this driver wrote one:
`0x102c` carries the rows the window spans, `0x1028`, `0x1078` and `0x1098` the
rows it stages.

**The weight buffer, and one register.** The buffer is **channel groups of
64**, each group laid out spatially inside itself, not one group of C. A group
of C puts a channel's nine taps `2C` bytes apart, 2048 at 1024 channels, and
the hardware could reach only one or two of the nine; a group of 64 puts them
128 apart whatever C is. The two are identical up to 64 channels, which is why
every depthwise here had matched within one count and the 1024 channel one had not. And
`DPU 0x4050` is not a constant for depthwise: its `SIZE_E_2` field counts
16-channel atomics,

```
SIZE_E_2 = (DIV_ROUND_UP(oc, 16) - 1) & 3
```

verified against vendor models compiled at ten channel counts from 16 to 1024,
three of them predicted before being compiled.

**How they were separated.** A channel that matches is not necessarily a
channel that computed: an output saturated by a large bias matches a reference
that is also saturated, and counting those separately took one model from an
apparent 9 of 32 to a real 1 of 32. Then **impulse models**, one live tap per
channel so the correct output is the input shifted by a known amount, which
ruled the wiring out and later located the reach. Then the **per row maxdiff
profile**, which put an error at a task boundary in one line of output. Every
round since has been written with its decision rule and a control that can
fail, and two readings were withdrawn that way.

## The first convolution: four literals

conv0 had never worked, and it was never in the regression set, so it was not
measured until 2026-08-11. It takes its own code path whose register values are
literals from a single capture. Four were wrong, each found by a different
instrument and each with a control that reproduces it:

| what | was | is |
|---|---|---|
| the coefficient region | the fp16 scale table | left zero for a first conv |
| `CNA 0x1080`, padding amounts | `0x00000101`, symmetric 1 | derived from the layer |
| `CNA 0x1084`, pad value | `0x00808080` | `in_zp - 0x80`, replicated |
| `DPU 0x40ac/b0/b4`, requant | offset -2, `0x5391`, shift 25 | `out_zp - 0x80`, `0x76be`, shift 26 |

The coefficient region was an address collision: `0x5024` points at
`bias_addr + 0x100` on this path, and the table this driver started writing in
an earlier round is 256 bytes for 32 output channels, so it landed exactly on
the second operand. The padding was symmetric one on every side, which is what
a `padding=1` convolution asks for; tflite SAME padding on a 224 to 112 stride
2 layer needs one pad in total, so it belongs on the other corner. An impulse
first conv decoded to the input shifted one pixel up and left, on all 32
channels at correlation 1.000, which is what named it.

The requant is the one worth reading twice. The comment above those literals
said computing them gives offset -128, scale `0x76be` and shift 22, "which is
wrong for conv0". The offset and the scale were right and the shift was short
by four; treating the three as one captured triple, to be accepted or rejected
together, is what kept conv0 broken.

That took conv0 from an empty MAC to 99.5 percent of pixels exact, and the
remainder turned out to be a fifth thing, in one column.

**The right hand pad does not work.** With tflite SAME on a 224 wide image at
stride 2 the single pad lands after the image, so output column 111 is the only
one that reads a padded tap and `kx = 2` is the only tap that reaches it. That
tap is fed a raw zero, before the CNA's per lane values are applied, so with
those at -128 it contributes `-128 * w` instead of nothing. Nothing in the
register file steers that byte: the pad value register was swept over four
values and only the row pad moved, the fourth lane's value is inert, and of the
two trailing pad fields in `0x1080` one is load bearing and the other changes
nothing at all.

So this driver stopped asking for it. The input is widened in memory to the
first whole number of feature atomics past what the last window reads, the added
columns hold the input zero point, and the CNA is told the image is that wide.
For 224 that is 240, where `240 * 3` is a round 45 of the 16 byte units. Six
registers carry the width and each one reproduces its previous literal exactly
at 224, which is how they were identified. **conv0 is now 32 of 32.**

## Chaining works, and the row window is a CBUF budget

Chained operations needed no change at all. The long standing "op2 fails" was
the individual operators failing, and it went away when they were fixed.
`conv0` into a depthwise comes out 28 of 32 at maxdiff 3, and simulating both
operators offline with the hardware's own arithmetic reproduces the board
exactly, down to the same four channels: they are the CPU reference's own
rounding spread through the second operator's window, not a defect.

That simulation settled a larger question too. Every model here carries a one
sided off by one population against the tflite reference, worst at 85.50
percent of interior pixels exact with all 56125 misses one count low, and it is
**the reference, not the hardware**. tflite's requant is a
`SaturatingRoundingDoublingHighMul` followed by a `RoundingDivideByPOT`, and for
a multiplier of 0.2922 its final divide is by two, so the intermediate lands on
exactly one half for half the pixels and rounds up every time. Emulating that
offline reproduces four models to the pixel, while comparing the hardware
against exact arithmetic gives 99.97 to 99.99 percent. `maxdiff <= 1` was the
right pass mark all along.

**One task can stage about 2560 entries of input CBUF, five banks**, where the
bank arithmetic hands out fifteen. Nothing checked, so any layer over the budget
produced garbage on the whole surface. Holding the channel count fixed and
walking the width separates it from a channel count limit:

| layer | input entries | output channels correct |
|---|---|---|
| 64 channels, 70 wide | 2450 | 64 / 64 |
| 64 channels, 72 wide | 2592 | 0 / 64 |
| **128 channels**, 44 wide | 1936 | **128 / 128** |
| **32 channels**, 111 wide | 3108 | **0 / 32** |

The last two come out the opposite way to what a channel count story predicts
for both. And the 91 rows this driver had hardcoded as its row window is that
same budget divided by the single layer it was measured on: 2560 over 28 entries
per row is 91.4. Deriving it reproduces that 91 exactly for its own case and
fixes the sizes the literal got wrong.

The two faults this section used to end on are both closed. The odd input width
was a truncating division in the CBUF surface stride, and the turnover at 64
channels was the 1x1 weight layout: see the MobileNet section above.

Full ledger: **[FINDINGS.md](FINDINGS.md)**, newest first, including the
retractions, of which there have been several.

| | |
|---|---|
| SoC | RK3576 (Cortex-A72 × 4 + Cortex-A53 × 4) |
| Board | Radxa ROCK 4D |
| Kernel | linux-next, v8 is based on next-20260814 |
| Driver | `drivers/accel/rocket` (DRM-accel, merged in 6.18) |

## Status

The v8 series was run on a ROCK 4D with nothing else applied (2026-08-17):

```
[    1.284413] [drm] Initialized rocket 0.0.0 for rknn on minor 0
[    1.286304] rocket 27700000.npu: Rockchip NPU core 0 version: 1179210311

  29:  0 ... GICv2 279 Level  27702000.iommu, 27700000.npu     before three submits
  29:  3 ... GICv2 279 Level  27702000.iommu, 27700000.npu     after
```

Three submits, three interrupts, one each. The three used different inputs, so
a stale output buffer could not pass: every earlier "byte exact N times in a
row" figure in this project fed the same input each time and could not tell a
recomputation from an untouched buffer.

`/dev/accel/accel0` present, unbind and rebind clean, no warning in dmesg.
Earlier boot log: <https://gist.github.com/gahingwoo/7543c1be83c8b8ec15727a8f11a4873c>

**What v8 does not survive is a job timeout**, which is why there is a v9.
`rocket_reset()` called `pm_runtime_put_noidle()`, which drops the usage count
without starting the idle path, so the core stayed runtime active, the power
domain never dropped, the bus reset the domain cycles on power on never fired,
and the MMU stopped answering. Measured three runs in one boot with one variable
between them, each forcing a timeout and then running the same convolution:

| put | after the timeout | the next inference |
|---|---|---|
| `put_noidle` | runtime active, rail up | 0 of 128, `MMU_DTE_ADDR` |
| `put_autosuspend` | suspended, rail down | 128 of 128, no message |
| `put_noidle` again | runtime active, rail up | 0 of 128, `MMU_DTE_ADDR` |

The third run is there so the failure reads as deterministic rather than
intermittent. Igor Paunovic reported the observation this came from, and on
RK3588 his resets drop the domain either way, so it may be RK3576 only.

⚠ On a board built from this tree the fix is behind `rocket.reset_autosuspend=1`
and **defaults off**. A long test round that hits one timeout will otherwise run
every entry after it on a dead block, which is exactly what happened to round
250 and cost thirty entries.

## Patches

The upstream series is the lore link above, and everything in it is now posted;
the `PC_TASK_CON` fix that used to live only here went out with v7.

`kernel/` carries the working tree this project tests with, which is a
superset: it keeps instrumentation and probes that are not upstream material,
such as register tracing and an `rk_iommu` `flush_iotlb_all` that has not been
submitted. None of it is needed for the driver to work, which the v8
verification run above measured directly by leaving all of it out.

The Mesa side has its first upstream-shaped slice open as
[mesa!43804](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/43804),
five patches and 711 lines for one regular convolution, posted and not yet
reviewed. It is narrow on purpose and declines the depthwise, pointwise and
image-input types MobileNet is built from, so the end to end result above comes
from the development tree rather than from it. The rest still lives in
`mesa-patches/` as a series against `gitlab.freedesktop.org/mesa/mesa`.

## Build

Requires meson, ninja, and aarch64 cross toolchain (buildroot fetches its own).

```bash
./build.sh        # full pipeline: kernel + Mesa + rootfs + sdcard.img (~30 min first run)
./kernel-only.sh  # kernel + DTB only (~5 min)
```

## Flash

```bash
# Confirm /dev/sdX is a real block device before writing:
file /dev/sdX   # must say "block special"

sudo dd if=buildroot/br-out/images/sdcard.img of=/dev/sdX \
    bs=4M conv=fsync oflag=direct status=progress
# SDR50 card writes at ~17 MB/s; if you see > 100 MB/s the write is going to
# page cache only and the card will boot with a corrupt journal.

# Verify the write before booting:
sudo cmp -n $(stat -c%s buildroot/br-out/images/sdcard.img) \
    buildroot/br-out/images/sdcard.img /dev/sdX && echo "OK"
```

## Verify on board

```bash
dmesg | grep -i rocket
ls /dev/accel/
```

## Layout

```
build.sh                     full pipeline (extract → mesa → model → buildroot → sdcard.img)
kernel-only.sh               fast kernel iteration
kernel/
  000[1-2]-*.patch           2-patch DTS series for upstream submission
  npu.fragment               CONFIG_DRM_ACCEL + ROCKET + CRC32C
  base.config                linux-next .config snapshot (regenerated by build.sh)
mesa/
  build-mesa.sh              Mesa -Dgallium-drivers=rocket -Dteflon=true
buildroot/
  configs/rock4d_npu_defconfig
  board/rock4d/post-image.sh assembles sdcard.img
rootfs-overlay/
  opt/npu-test/
    bringup-check.sh         probe + inference verification (run as root on board)
    infer.py                 Teflon MobileNetV1 UINT8 inference driver
    install.sh               first-run: pip3 install tflite-runtime
    perch.py                 per output channel comparison against the CPU, and
                             the instruments the rounds were read with
    *.tflite                 models (downloaded or generated, gitignored)
  usr/lib/libteflon.so       Mesa Teflon TFLite delegate
vendor-capture/
  make_dw_geom.py            rebuilds every geometry probe model by byte patching
                             ones already in the tree, since .tflite is gitignored
                             and there is no tensorflow here to build them with
notes/
  rk3576-npu-values.md       hardware register/clock/IRQ values with provenance
  provenance.md              CONFIRMED / UNVERIFIED table
```
