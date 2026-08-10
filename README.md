# linux-rk3576-npu

Mainline kernel bring-up for the RK3576 NPU on Radxa ROCK 4D.

## Upstream

The driver support is on the list. Current series:

**[RFC PATCH v6 0/9: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/20260806063413.350184-1-gahing@gahingwoo.com/)**
(2026-08-06, on top of Igor Paunovic's clocks-by-name fix)

Earlier revisions:
[v1](https://lore.kernel.org/all/20260717085220.3212274-1-gahing@gahingwoo.com/) |
[v2](https://lore.kernel.org/all/20260718031146.3368811-1-gahing@gahingwoo.com/) |
[v3](https://lore.kernel.org/all/20260731043507.1832277-1-gahing@gahingwoo.com/) |
[v4](https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/) |
[v5](https://lore.kernel.org/all/20260805063826.95682-1-gahing@gahingwoo.com/)

v6 splits the driver work into preparation and enablement, adds bindings for the
power domain resets and for the NPU MMU clock set, and fixes five things found by
review: a one way poll_dying latch, a reset count that walked an unacquired
entry, two register writes that belonged under job_lock, a poll that could touch
a runtime suspended device, and a completion race that v5 had closed on only one
side. Reviewers so far: Chaoyi Chen, Krzysztof Kozlowski, Alexey Charkov, Heiko
Stuebner, Tomeu Vizoso, Philipp Zabel, Diederik de Haas and Igor Paunovic, who
provides the RK3588 coverage this project cannot produce.

Since v6 the interrupt claim in every cover letter has been
[corrected on the list](https://lore.kernel.org/all/20260807211629.1573228-1-gahing@gahingwoo.com/):
the completion interrupt works, and the polling in patch 7 should not exist. v7
drops it, splits the `job_lock` fix into its own patch with a Fixes tag,
separates the `rk3588_soc_data` change from adding `rk3576_soc_data`, and puts
the refactoring before the new support rather than inside it.

Two iommu patches from the same work are already merged, in linux-next since
next-20260727: `841363ebb508` ("iommu/rockchip: Take all DT clocks") and
`b10d5920cafa` ("iommu/rockchip: Clear stale page faults before enabling
stall").

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
list](https://lore.kernel.org/all/20260807211629.1573228-1-gahing@gahingwoo.com/);
v7 drops the poll.

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

## Depthwise: the overlap rows were staged twice

Fixed 2026-08-11. A MobileNet depthwise layer is now correct on every output
channel:

| model | before | after |
|---|---|---|
| impulse, 112x112, 32 channels | 0 / 32 | **32 / 32** |
| MobileNet dw1, 112x112, 32 channels | 9 / 32, of which 1 real | **32 / 32** |
| row maxdiff, sampled every 8th row | `1 x12, 200, 200` | **`1` everywhere** |

A 112 wide layer does not fit in the CBUF at once, so it is dispatched as row
windows, 90 output rows then 22. Each window overlaps the one before it by a
row on each side, and those rows are **already staged**: the reuse base at
`CNA 0x103c` points back at them, and this driver computed that correctly.
`rkt_split_tasks` then staged them **again**, writing them a second time at the
next free CBUF row, so every row after the overlap sat two rows late and the
window convolved shifted input.

The vendor's capture of the same layer writes **two different row counts** for
its second window where this driver wrote one:

| register | vendor | means | this driver was |
|---|---|---|---|
| `0x102c` | 23 | rows the window **spans** | 23, correct |
| `0x1028` | 21 | rows it **stages** | 23, wrong |
| `0x1078` | 21 | the same | 23, wrong |
| `0x1098` | 21 | the same | 23, wrong |

The fix is not tuned to one boundary: with the seam moved to 46 rows, giving
three windows, and to 64, giving two, the surface is still correct everywhere.
`ROCKET_STAGE_ALL=1` restores the old behaviour and reproduces the breakage
exactly.

**Why it hid for months.** Every regular model in this project is 80x80 or
smaller and takes the single task path. Nothing that tiled was ever correct and
nothing that was correct ever tiled, so no comparison between the two cases
existed, and every sweep of the coefficient buffer came back flat because the
coefficients were already right.

Three instruments made it findable, in order. A channel that matches is not
necessarily a channel that computed: an output saturated by a large bias
matches a reference that is also saturated, and reporting those separately took
one model from an apparent 9 of 32 to a real 1 of 32. Then an **impulse model**,
one live tap per channel so the correct output is the input shifted by a known
amount, which ruled the wiring out. Then the **per row maxdiff profile**, which
put the error at a task boundary in one line of output.

**Also corrected**: earlier notes here said a vendor `.rknn` compiled as
depthwise carries no per channel coefficient table. It carries none because
librknnrt builds it at load time. Resolving a runtime capture's address
registers back into the captured buffers finds it immediately, 48 byte records
of `[A 8 x int32][C 8 x int16]` with no B, and both terms reproduce from the
model with nothing fitted, for all 32 channels of a depthwise and a regular
layer that differ only in `groups`.

**What still does not compute**: a depthwise at 1024 channels, chained
operations, and MobileNet, which contains both. The 1024 channel case is not
the same bug and is now well characterised: the impulse decodes to a perfect
single tap of the **right input plane**, correlation 1.000, and the **wrong
tap**, by `(-p) mod 9`. It is the one depthwise shape small enough not to be row
windowed, and a layer that does not window is given different CNA words.

Full ledger: **[FINDINGS.md](FINDINGS.md)**, newest first, including the
retractions.

| | |
|---|---|
| SoC | RK3576 (Cortex-A72 × 4 + Cortex-A53 × 4) |
| Board | Radxa ROCK 4D |
| Kernel | linux-next ≥ 7.2-rc5 (20260730) |
| Driver | `drivers/accel/rocket` (DRM-accel, merged in 6.18) |

## Status

NPU probe verified on hardware (2026-06-07):

```
[    1.230794] [drm] Initialized rocket 0.0.0 for rknn on minor 0
[    1.232935] rocket 27700000.npu: Rockchip NPU core 0 version: 1179210311
```

`/dev/accel/accel0` present. Full boot log: <https://gist.github.com/gahingwoo/7543c1be83c8b8ec15727a8f11a4873c>

## Patches

The upstream series is the lore link above. `kernel/` additionally carries the
working tree this project tests with, which is ahead of what has been posted:
the `PC_TASK_CON` fix lives there, and the Mesa register fixes are in
`mesa-patches/`.

```
0001  arm64: dts: rockchip: rk3576: add RKNN NPU subsystem
0002  arm64: dts: rockchip: rk3576-rock-4d: enable NPU core 0
```

Apply:

```bash
cd /path/to/linux-next
git am /path/to/linux-rk3576-npu/kernel/000*.patch
```

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
    *.tflite                 MobileNetV1 model (downloaded by build.sh, gitignored)
  usr/lib/libteflon.so       Mesa Teflon TFLite delegate
notes/
  rk3576-npu-values.md       hardware register/clock/IRQ values with provenance
  provenance.md              CONFIRMED / UNVERIFIED table
```
