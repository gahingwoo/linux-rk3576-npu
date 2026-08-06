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

Two iommu patches from the same work are already merged, in linux-next since
next-20260727: `841363ebb508` ("iommu/rockchip: Take all DT clocks") and
`b10d5920cafa` ("iommu/rockchip: Clear stale page faults before enabling
stall").

## ⚠ Inference is not correct yet

Bring-up works: the NPU probes, powers up and down through runtime PM, and runs
jobs to completion. A convolution submitted right after a resume is byte exact
against the CPU reference.

**Only the first submit after a reset computes.** Every submit after it is a no
op: it does not write its output buffer at all, so what userspace reads back is
whatever was in that buffer already. Measured on 2026-08-06 with one
configuration and two different inputs, checksumming one latched output BO:

| step | result | crc32 |
|---|---|---|
| A(input X), first submit of the session | correct | `20a556ae` |
| A(input Y), no reset in between | wrong | `20a556ae` (unchanged) |
| A(input Y), after a runtime resume | correct | `dda67317` |

The third row moves the checksum, so it does see the block's writes. The second
does not, with the same configuration loaded and only the input data different.

This corrects a long run of earlier writeups here, including three cover letters
on the list. "Re-running the same convolution is byte exact six for six" was
real as an observation and worthless as evidence: every one of those runs fed
the same input, and a stale buffer is indistinguishable from a correct
recomputation under that test. They were stale. So "A works, B fails, A works
again" never needed a story about configurations: A computes, B is a no op and
its freshly zeroed buffer reads back as the zero point, and A again is a no op
returning A's old result.

Two leads are retired by that. Tomeu Vizoso's ping-pong register bank, where the
pointer really is stuck but nothing the driver does moves it and the vendor does
not switch banks per submit either; and Igor Paunovic's alternative that the
block keeps running the resident configuration and writes the previous task's
addresses, which the same run refutes, because the resident buffer is unchanged
across the failing submit.

The open question is now narrower: why does the block accept exactly one task
per reset. Nothing measured so far says anything about the multiply accumulate,
and the userspace side was never involved.

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

2-patch series in `kernel/`, against linux-next-20260527.
Driver and binding changes are already merged upstream (linux 6.18).

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
