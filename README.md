# linux-rk3576-npu

Mainline kernel bring-up for the RK3576 NPU on Radxa ROCK 4D.

MobileNet V1 runs end to end on the NPU as of 2026-08-13: 995 of its 1001
outputs are within one count of the CPU reference. Details below.

## Companion projects

Three repositories, one board. The third name is a joke about the second: char siu
is Cantonese barbecue pork, eaten across Guangdong, Hong Kong and Malaysia, and a kiln is the
oven it is roasted in.

| repo | what it is |
|---|---|
| **linux-rk3576-npu** | this one: the open RK3576 NPU driver and Mesa work. `rocket` on the list, Teflon in Mesa, and the register knowledge the other two are built on |
| [kiln](https://github.com/gahingwoo/kiln) | the **vendor** RKLLM/RKNN stack on a mainline kernel. LLM and vision on the board today, through a closed runtime, and the yardstick the open stack is measured against |
| [charsiu](https://github.com/gahingwoo/charsiu) | an open **LLM** runtime for this NPU on the open driver. Day one; it starts by reading what the vendor asks the hardware to do |

## Upstream

The driver support is on the list. Current series:

**[PATCH v7 0/10: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/20260812094106.1391698-1-gahing@gahingwoo.com/)**
(2026-08-12, on top of Igor Paunovic's clocks-by-name fix)

Earlier revisions:
[v1](https://lore.kernel.org/all/20260717085220.3212274-1-gahing@gahingwoo.com/) |
[v2](https://lore.kernel.org/all/20260718031146.3368811-1-gahing@gahingwoo.com/) |
[v3](https://lore.kernel.org/all/20260731043507.1832277-1-gahing@gahingwoo.com/) |
[v4](https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/) |
[v5](https://lore.kernel.org/all/20260805063826.95682-1-gahing@gahingwoo.com/) |
[v6](https://lore.kernel.org/all/20260806063413.350184-1-gahing@gahingwoo.com/)

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

The v7 branch was run on the board before it was sent, with none of this
repository's out of tree patches applied, including no `rk_iommu`
`flush_iotlb_all`: three submits with three different inputs are byte exact
each time, the NPU's interrupt count goes from zero to three across them, and
probe, unbind and rebind are clean with no warning.

Reviewers so far: Chaoyi Chen, Krzysztof Kozlowski, Alexey Charkov, Heiko
Stuebner, Tomeu Vizoso, Philipp Zabel, Robin Murphy, Diederik de Haas and Igor
Paunovic, who provides the RK3588 coverage this project cannot produce.

Two iommu patches from the same work are already merged, in linux-next since
next-20260727: `841363ebb508` ("iommu/rockchip: Take all DT clocks") and
`b10d5920cafa` ("iommu/rockchip: Clear stale page faults before enabling
stall").

## MobileNet V1 runs end to end (2026-08-13)

The whole network now produces a real classification on the NPU with the open
stack: **995 of its 1001 outputs land within one count of the CPU reference**,
with the same ten distinct values the CPU produces. Every run before this one
was 1001 channels of zero.

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

Still open, all in Mesa: an **odd** output channel count is wrong across its
whole second weight tile (the CNA counts output channels in pairs and is told a
padded count by the vendor; the fix is written and not yet on the board), a
pointwise with **56** output channels times the NPU out, and **33** input
channels is wrong for a reason the packed row cost did not cover.

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
every depthwise here had been byte exact and the 1024 channel one had not. And
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
| Kernel | linux-next ≥ 7.2-rc5 (20260730) |
| Driver | `drivers/accel/rocket` (DRM-accel, merged in 6.18) |

## Status

The v7 series was run on a ROCK 4D with nothing else applied (2026-08-12):

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

## Patches

The upstream series is the lore link above, and everything in it is now posted;
the `PC_TASK_CON` fix that used to live only here went out with v7.

`kernel/` carries the working tree this project tests with, which is a
superset: it keeps instrumentation and probes that are not upstream material,
such as register tracing and an `rk_iommu` `flush_iotlb_all` that has not been
submitted. None of it is needed for the driver to work, which the v7
verification run above measured directly by leaving all of it out.

The Mesa side is not upstream at all yet and lives in `mesa-patches/` as a
patch series against `gitlab.freedesktop.org/mesa/mesa`.

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
