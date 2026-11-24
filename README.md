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

For Windows on Arm, [woa-rk3576-npu](https://github.com/gahingwoo/woa-rk3576-npu)
is a Windows driver for the same NPU, following `rocket`'s job model. charsiu
runs on it and decodes Llama-3.2-1B at 14 to 16 tokens a second on a
TaishanPi 3M under Windows 11 23H2 (2026-11-24).

## Upstream

Current series:

**[PATCH v18 0/8: accel/rocket: RK3576 NPU (RKNN) enablement](https://lore.kernel.org/all/cover.1795478392.git.gahing@gahingwoo.com/)**
(2026-11-24, on next-20261120)

Where the pieces are:

- pmdomain (the RK3576 NPU domain supply, the NPUTOP/VOP settle delay, and
  the probe fix for boards that leave the NPU disabled): applied by Ulf
  Hansson, 1/3 to fixes (`458777762756`), 2/3 and 3/3 to next
  (`b1bff9ced657`, `adc13316e6d9`).
- accel/rocket 1-4 of v17: in v7.4-rc4, through drm-misc-fixes.
- accel/rocket, dt-bindings and DTS, the remaining 8: v18 above. It answers
  Daniel Drake's review of v17: the clocks and resets come from the
  devicetree, GET_PARAM comes before the RK3576 patch, and the RK3576
  TASK_CON is a generated register definition.
- iommu: two patches merged earlier (`841363ebb508`, "iommu/rockchip: Take
  all DT clocks", and `b10d5920cafa`, "iommu/rockchip: Clear stale page
  faults before enabling stall"), and one sent on 2026-11-24 for the known
  issue below:
  [iommu/rockchip: Disable paging on banks that still page before a force reset](https://lore.kernel.org/all/20261123235154.315460-1-gahing@gahingwoo.com/).

Known issue: after a job timeout, the core reset can leave bank 0 of the
NPU IOMMU paging, and the NPU then does not recover. Without the iommu fix,
about one in every 2 to 10 back-to-back forced timeouts is not recovered
from; with it, 20 in a row recovered (board-logs/r429).

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
[v13](https://lore.kernel.org/all/20260915104328.45901-1-gahing@gahingwoo.com/) |
[v14](https://lore.kernel.org/all/20260924102135.92217-1-gahing@gahingwoo.com/) |
[v15](https://lore.kernel.org/all/20261101082307.151957-1-gahing@gahingwoo.com/) |
[v16](https://lore.kernel.org/all/20261108065917.135194-1-gahing@gahingwoo.com/) |
v17 ([pmdomain](https://lore.kernel.org/all/cover.1794615323.git.gahing@gahingwoo.com/),
[rocket](https://lore.kernel.org/all/cover.1794615324.git.gahing@gahingwoo.com/))

Reviewers so far: Chaoyi Chen, Krzysztof Kozlowski, Conor Dooley, Alexey
Charkov, Heiko Stuebner, Tomeu Vizoso, Philipp Zabel, Robin Murphy, Ulf Hansson,
Abel Vesa, Daniel Drake, Diederik de Haas and Igor Paunovic. Sidong Yang tests
on the RK3588, which this project cannot do, and Vladimir Bely on a NanoPi R76S.

## Status

| | |
|---|---|
| SoC | RK3576 (Cortex-A72 × 4 + Cortex-A53 × 4) |
| Boards | Radxa ROCK 4D, ArmSoM CM5 on the CM5-IO carrier |
| Kernel | v7.4-rc4 with v18 and the iommu fix (ROCK 4D, fork CI image, board-logs/r429); Armbian edge 7.3 with v14 (Armbian's own build); next-20261105 with v16 (the CI) |
| Driver | `drivers/accel/rocket` (DRM-accel, merged in 6.18) |

Armbian has merged v14 for both boards (armbian/build#11162 CM5-IO and
#11163 ROCK 4D, 2026-11-02), and its edge kernel enables the NPU on both.

The ROCK 4D now runs v7.4-rc4 with v18 (board-logs/r429): both NPU cores
probe, GET_PARAM returns 2, 30 runs in a row give the same text with no
error, three boots with the NPU disabled switch NPUTOP, NPU0 and NPU1 off,
and with the iommu fix 20 back-to-back forced job timeouts all recover.

## Using it on Armbian

On a ROCK 4D or an ArmSoM CM5-IO running Armbian with the edge kernel, the NPU
works out of the box, and charsiu is in the Armbian repository:

```bash
sudo apt install charsiu
```

`ls /dev/accel/` shows `accel0` when the kernel drives the NPU. The edge kernel
in apt.armbian.com still predated the merge on 2026-11-09; the one in
beta.armbian.com carries it.

## Getting a kernel

Armbian's edge kernel for rockchip64 carries the series, and that is the kernel
the charsiu installer offers on a system whose kernel cannot drive the NPU: it
takes `linux-image-edge-rockchip64` and `linux-dtb-edge-rockchip64` from
beta.armbian.com and unpacks them into place.

The [releases](https://github.com/gahingwoo/linux-rk3576-npu/releases) here are
kernels with patches under test, built by the CI from linux-next. The latest
one is next-20260914 with v14; the CI now builds next-20261105 with v16, and a
release of that has not been cut. Each carries `Image`, `rk3576-rock-4d.dtb`,
the modules, the `.config`, and a `MANIFEST` naming every patch that went in.

To build what the CI builds now, follow `.github/workflows/kernel.yml`, which
is what the releases come from. In short:

```bash
git clone --depth 1 --branch next-20261105 \
    https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git
cd linux-next
for p in ../linux-rk3576-npu/rfc-send-v16/v16-00*.patch \
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
                       cover, and a SENT.md from v10 on; v18 is current
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
