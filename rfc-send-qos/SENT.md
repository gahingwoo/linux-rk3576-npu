# pmdomain: rockchip: do not restore QoS that was never saved

Sent 2026-11-01 05:56 UTC, one patch, server result 250.

- Message-ID: `20261101055633.101309-1-gahing@gahingwoo.com`
- lore: https://lore.kernel.org/all/20261101055633.101309-1-gahing@gahingwoo.com/
- base: next-20261030 (`7649ba73f9e7`)
- To: Ulf Hansson, Heiko Stuebner
- Cc: Sebastian Reichel, Shawn Lin, Finley Xiao, Elaine Zhang (author of
  074c6a422d86, which the Fixes tag names), linux-pm, linux-rockchip,
  linux-arm-kernel, linux-kernel

Not part of the RK3576 NPU series. It fixes the GPU, on plain mainline.

The evidence is board-logs/r423: three kernels on a CM5-IO with a print
after rockchip_pmu_restore_qos(). Without the fix the GPU's QoS reads all
zeros after its first power-on, also with none of the NPU series applied;
with it the GPU keeps priority 0x101, mode 3, bandwidth 0x80, saturation 8.
Rockchip's BSP driver has the same is_qos_saved flag.

Tested on RK3576 only. RK3588 goes through the same code and was not run.

The same commit is also 09/16 of the prepared v15 of the NPU series, which
is not sent; if this lands first, v15 drops it.
