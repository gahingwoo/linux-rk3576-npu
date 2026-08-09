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

## ⚠ Inference is correct for one convolution shape, not yet in general

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

**That also corrects a claim carried in all six cover letters.** The completion
interrupt does reach the GIC on RK3576. It never fired because the PC believed
it had 28672 tasks left. With the fix and the poll disabled, so only a real
interrupt can retire a job, a convolution runs three times out of three with
zero timeouts. [Correction sent to the
list](https://lore.kernel.org/all/20260807211629.1573228-1-gahing@gahingwoo.com/);
v7 drops the poll.

**What computes today**, each confirmed with an A/B control in a single boot and
a control model passing at both ends of the run:

| convolution | |
|---|---|
| 5x5 stride 2, 16 in, 128 out | correct, byte exact against the CPU above the output zero point |
| 5x5 stride 1, 16 in, 128 out | correct |
| 5x5 stride 2, 16 in, 16 out | correct |

The last two are new, from two Mesa fixes where a register had been filled from
a constant fitted to a capture rather than derived:

- `CNA 0x1080` is the **padding** register,
  `(pad_right << 24) | (pad_bottom << 16) | (pad_left << 8) | pad_top`. The
  constant it replaced, `0x02020101`, is exactly SAME padding for a 5x5 stride 2
  convolution, so every other geometry was configured with the wrong padding or
  with none.
- `DPU 0x4050` depends on the **output channel count**: `0x80011111` for a
  multiple of 32 and `0x80011011` otherwise, ten for ten across a sweep.

Both were found by compiling vendor `.rknn` files on the host at chosen
geometries and reading the registers back, which the RKNN toolkit supports from
ONNX on arm64. That turns "what does the vendor put here" into a question
answerable without the board.

**What does not compute: anything with a kernel smaller than 5x5.** Cropping the
working model's own kernel to its centre 3x3 or 1x1, which leaves the bias, the
scales and the output shape untouched, breaks it. For those the driver's output
has been verified against a vendor build at the same geometry and matches: the
register stream in absolute terms, the weight buffer layout including the
32-channel grouping, the bias, the requant, and the A, B and C coefficients. An
input impulse lands in exactly the right output pixels, so no tap is paired with
the wrong input. The simplest failing case is a constant input at the input zero
point, where every MAC product is zero by construction and the answer must be
`requant(bias)`: 5x5 returns exactly that, 3x3 returns the zero point
everywhere, and 1x1 returns values below the zero point that the same clamp
forbids at 5x5.

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
