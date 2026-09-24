# linux-rk3576-npu

Mainline kernel bring-up for the RK3576 NPU on Radxa ROCK 4D.

MobileNet V1 runs end to end on the NPU and **returns the right label**: on the
test image it picks class 754, the class the CPU reference picks, with the CPU's
top five in the same order. Every one of its layers, run on its own, is **99.93
to 99.99 percent of pixels identical to exact integer arithmetic**, which is
closer than the tflite interpreter most of the numbers here are scored against.

An open LLM runtime runs **Llama-3.2-1B entirely on this NPU at four bits**,
through this driver and nothing else, at **17.85 to 18.60 tokens a second**
depending on the NPU clock, with the sentence identical to the one the exact
arithmetic writes. Rockchip's own runtime was run here too, on this board
against this board's own mainline kernel, and reads 12.85 at 594 MHz and 12.73
at 786. So the margin is 1.39x at one clock and 1.46x at the other, and it
belongs to the condition rather than to either runtime; the two need different
drivers, so they cannot share a boot and each column is its own. At one row per
dispatch the NPU reads its weights at 8.3 to 9.4 GB/s, which is what one CPU
core of this board measures against DRAM on the same boot, so **what is left to
win at decode is bytes, not calls**. The rounds behind those figures are
charsiu's `docs/paper-evidence.md` sections 1b, 5a and 5b; how MobileNet got
there is in [HISTORY.md](HISTORY.md).

## Companion projects

Three repositories, one board. The third name is a joke about the second: char siu
is Cantonese barbecue pork, eaten across Guangdong, Hong Kong and Malaysia, and a kiln is the
oven it is roasted in.

| repo | what it is |
|---|---|
| **linux-rk3576-npu** | this one: the open RK3576 NPU driver and Mesa work. `rocket` on the list, Teflon in Mesa, and the register knowledge the other two are built on |
| [kiln](https://github.com/gahingwoo/kiln) | the **vendor** RKLLM/RKNN stack on a mainline kernel. LLM and vision on the board today, through a closed runtime, and the yardstick the open stack is measured against |
| [charsiu](https://github.com/gahingwoo/charsiu) | an open **LLM** runtime for this NPU on the open driver. It reaches the NPU through `rocket` on its own and runs Llama-3.2-1B end to end at four bits, about 18 tokens a second, with no Mesa and no vendor runtime in the path |

## Upstream

The driver support is on the list. Current series:

**[PATCH v14 0/15: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/20260924102135.92217-1-gahing@gahingwoo.com/)**
(2026-09-24, applies to a plain next-20260914)

Nothing is applied yet. Ulf Hansson has offered to take the three pmdomain
patches, 7, 9 and 10, through his tree; the rest goes through accel and
rockchip. Fourteen review tags are on it: Igor Paunovic's Tested-by on 2, 3 and
4 and Reviewed-by on 5, Krzysztof Kozlowski's Reviewed-by on the npu binding,
Conor Dooley's Acked-by on 7 and 8, Heiko Stuebner's Reviewed-by on 7, Abel
Vesa's on 9 and 10, and four on 1/15, which is Igor's clocks-by-name patch
carried in the series: three from his posting and ours.

v14 answers the v13 review: one reset instead of an array in 10 (Philipp Zabel),
the reset pointer cleared under the lock on removal (Sashiko), v13's 13/14 split
in two (Heiko), and shorter messages throughout (Ulf and Heiko). It also
corrects two numbers v12 and v13 carried: the rail test is 11 to 25 wrong words
a pass, not 13 to 20 wrong rows, and the three-input convolution test was within
one count, not byte exact.

Heiko asked whether 9's settle delay is for the domain or the rail. Measured on
v13 as posted: with the delay at 0 the first power-on of the NPU domain takes an
async SError, also with the rail forced always-on; with 15 us, 536 cold
power-ons are clean (board-logs/r420). Chaoyi Chen of Rockchip gave the same
answer from the design: about 15 us of internal preparation, during which the
QoS registers must not be touched.

Why 594 MHz: CLK_RKNN_DSU0 clocks both cores and nothing in mainline sets its
rate or the NPU rail, so the block comes up at 786 MHz on the 750 mV this
board's PMIC boots with, and two cores running together then write wrong words,
11 to 25 in each pass of 5400 rows. 14/15 assigns 594 MHz, which is clean and
sits between the 500 and 600 MHz steps of Rockchip's OPP table, both of which
ask 725 mV.

The race 3/15's lock scope closes has no hardware proof. Igor reached the path
on RK3588 with a two-task job and saw no fault, and says that does not show the
race closed. On this RK3576 the protocol that would reach it, JOB_TIMEOUT_MS=2,
takes the PMIC's I2C down and leaves two CPUs not answering an NMI, so it cannot
be run here.

Earlier revisions:
[v1](https://lore.kernel.org/all/20260717085220.3212274-1-gahing@gahingwoo.com/) |
[v2](https://lore.kernel.org/all/20260718031146.3368811-1-gahing@gahingwoo.com/) |
[v3](https://lore.kernel.org/all/20260731043507.1832277-1-gahing@gahingwoo.com/) |
[v4](https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/) |
[v5](https://lore.kernel.org/all/20260805063826.95682-1-gahing@gahingwoo.com/) |
[v6](https://lore.kernel.org/all/20260806063413.350184-1-gahing@gahingwoo.com/) |
[v7](https://lore.kernel.org/all/20260812094106.1391698-1-gahing@gahingwoo.com/) |
[v8](https://lore.kernel.org/all/20260817113603.1436067-1-gahing@gahingwoo.com/) |
[v9](https://lore.kernel.org/all/cover.1787568658.git.gahing@gahingwoo.com/) |
[v10](https://lore.kernel.org/all/20260831040804.24111-1-gahing@gahingwoo.com/) |
[v11](https://lore.kernel.org/all/20260831081956.84871-1-gahing@gahingwoo.com/) |
[v12](https://lore.kernel.org/all/20260912065053.1519165-1-gahing@gahingwoo.com/) |
[v13](https://lore.kernel.org/all/20260915104328.45901-1-gahing@gahingwoo.com/)

Reviewers so far: Chaoyi Chen, Krzysztof Kozlowski, Conor Dooley, Alexey
Charkov, Heiko Stuebner, Tomeu Vizoso, Philipp Zabel, Robin Murphy, Ulf Hansson,
Abel Vesa, Diederik de Haas and Igor Paunovic, who provides the RK3588 coverage
this project cannot produce.

Two iommu patches from the same work are already merged, in linux-next since
next-20260727: `841363ebb508` ("iommu/rockchip: Take all DT clocks") and
`b10d5920cafa` ("iommu/rockchip: Clear stale page faults before enabling
stall").

## Status

| | |
|---|---|
| SoC | RK3576 (Cortex-A72 × 4 + Cortex-A53 × 4) |
| Board | Radxa ROCK 4D |
| Kernel | linux-next next-20260914 with the v14 series |
| Driver | `drivers/accel/rocket` (DRM-accel, merged in 6.18) |

The board runs v14, built by the kernel CI with the same config as the charsiu
release, read off it on 2026-09-24:
`7.3.0-rc3-next-20260914-00016-g8be156261ad4`. Both NPU cores probe, the full
regression is green with perplexity identical to the last digit
(board-logs/r421), and zram gives it 6 GB of zstd swap. What that run does NOT
do is exercise the race 3/15's lock scope closes; the Upstream section above
says why.

## Getting a kernel

The [latest release](https://github.com/gahingwoo/linux-rk3576-npu/releases/latest)
is the kernel the charsiu installer offers: next-20260914, the v14 series, the
one patch in `patches-extra/`, and the config the CI builds. It carries `Image`,
`rk3576-rock-4d.dtb`, the modules, the `.config`, and a `MANIFEST` naming every
patch that went in.

To build the same kernel, follow `.github/workflows/kernel.yml`, which is what
the releases come from. In short:

```bash
git clone --depth 1 --branch next-20260914 \
    https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git
cd linux-next
for p in ../linux-rk3576-npu/rfc-send-v14/v14-00*.patch \
         ../linux-rk3576-npu/patches-extra/[0-9]*.patch; do
    case "$p" in *-0000-*) continue ;; esac   # the cover letter
    git am "$p"
done
cp ../linux-rk3576-npu/kernel/base.config .config
# then the scripts/config lines from kernel.yml, and olddefconfig
make ARCH=arm64 -j"$(nproc)" Image dtbs modules
```

`DRM_ACCEL_ROCKET`, `STMMAC_ETH`, `DWMAC_ROCKCHIP` and `RTC_DRV_HYM8563` must end
up `=y`, not `=m`: a rootfs without udev never loads them, and `olddefconfig`
turns `=y` into `=m` on its own when a dependency moves. The CI checks all four.

## Images

`debian/` builds a Debian image for the ROCK 4D without root; see
[debian/README.md](debian/README.md).

`build.sh` and `kernel-only.sh` build the buildroot image the development board
started on. Both take the kernel from a local linux-next checkout whose path is
written into them, so they do not run as they are on another machine.

`flash.sh` writes either image to a card (`IMG=` picks which; the buildroot one is
the default):

```bash
file /dev/sdX                        # must say "block special"
sudo IMG=debian-rock4d.img bash flash.sh /dev/sdX   # debian/build-image.sh writes it here
```

## Verify on board

```bash
dmesg | grep -i rocket
ls /dev/accel/
```

## Mesa

The Mesa side has its first upstream-shaped slice open as
[mesa!43804](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/43804),
five patches and 745 added lines for one regular convolution, open since
2026-08-17 and rebased on 2026-09-01, with no review comment on it yet. It is
narrow on purpose and declines the depthwise, pointwise and image-input types
MobileNet is built from, so the MobileNet result above comes from the
development tree rather than from it. The rest lives in `mesa-patches/`.

## Layout

```
rfc-send-vNN/          every posting of the series as it was sent, with its
                       cover, and a SENT.md from v10 on; v14 is current
patches-extra/         built into the release kernel but not part of the
                       series (one dw-hdmi-qp fix); see its README
.github/workflows/     kernel.yml builds and releases the kernel;
                       patch-drift.yml checks weekly that the series still
                       applies to linux-next
kernel/base.config     the config the CI starts from
kernel/00*.patch       the working series as of 2026-08-25, debug probes
                       included; nothing builds from it now
board-logs/            one file per board round, rNNN-<what it found>.txt
debian/                Debian image without root
build.sh, buildroot/   the development board's buildroot image (local paths)
mesa/, mesa-patches/,  the Teflon work and its upstream merge request
  mesa-send/
rootfs-overlay/        files baked into the buildroot image
vendor-capture/        captures of the vendor stack, and the probe models
notes/                 hardware values with their provenance
```

## History

How it got here is in [HISTORY.md](HISTORY.md): the revisions from v7 on, and
the bring-up from the first convolution to MobileNet and the first LLM tokens.
The round by round ledger, retractions included, is [FINDINGS.md](FINDINGS.md),
and the board rounds since August are in `board-logs/`.
