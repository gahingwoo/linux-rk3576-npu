# linux-rk3576-npu

Mainline kernel bring-up for the RK3576 NPU on Radxa ROCK 4D.

## Upstream

The driver support is on the list. Current series:

**[RFC PATCH v4 0/6: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/)**
(2026-08-03, against next-20260730)

Earlier revisions: [v1](https://lore.kernel.org/all/20260717085220.3212274-1-gahing@gahingwoo.com/) |
[v2](https://lore.kernel.org/all/20260718031146.3368811-1-gahing@gahingwoo.com/) |
[v3](https://lore.kernel.org/all/20260731043507.1832277-1-gahing@gahingwoo.com/)

v4 is a fixes only revision: six bugs found in v3, five of them by the Sashiko
review bot, each checked against the vendor DT, the vendor driver or the board
before being believed. Igor Paunovic tested the v3 driver patch on RK3588, which
is hardware this project does not have.

Merged already, out of the v2 series:

| commit | |
|---|---|
| `841363ebb508` | iommu/rockchip: Take all DT clocks |
| `b10d5920cafa` | iommu/rockchip: Clear stale page faults before enabling stall |

## ⚠ Inference is not correct yet

Bring-up works: the NPU probes, powers up and down through runtime PM, and runs
jobs to completion. A single convolution is byte exact against the CPU
reference, and re-running that same convolution is byte exact every time, six
for six in one power session, with no reset in between.

What fails is loading a **different** configuration after it. The second one
computes nothing and writes out a zero point surface, while the one already
resident keeps working; going back to it is byte exact again, and the same
holds with the two models swapped. The register command list is identical in
both positions, byte for byte, so it is not what the driver programs. A full
NPU reset clears the condition: with one before every op, per layer input and
weight fetch return at the graph's real shapes and the DPU writes back, but
what lands is still zero point.

So dispatch, DMA and write back are all fine, and the multiply accumulate is
what produces nothing.

Tomeu Vizoso suggested on the list that this looks like the ping-pong register
bank never switching. The pointer is indeed stuck, and reading it back shows we
write S_POINTER bit 0 as 0 and it reads 1 on every job for the rest of the
session. But the driver cannot move it: flipping the bit, selecting a bank the
way the vendor's state_init does, and pulsing POINTER_PP_CLEAR all change
nothing, and the vendor does not switch banks per submit either. A read snapshot
of every block the driver can reach, 20 KB across pc, cna, core, dpu and rdma,
differs between a job that computed and one that did not in exactly one word,
and that word is OPERATION_ENABLE.

Full ledger: **[FINDINGS.md](FINDINGS.md)** (newest first, including the
retractions). Note that earlier writeups here described this as "only the first
task per power session computes"; that framing is wrong and was corrected on
2026-07-26.

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
./build.sh        # full pipeline — kernel + Mesa + rootfs + sdcard.img (~30 min first run)
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
