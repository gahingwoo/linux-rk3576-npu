# SENT 2026-11-24

[PATCH] iommu/rockchip: Disable paging on banks that still page before a force reset

- Message-ID: <20261123235154.315460-1-gahing@gahingwoo.com>
- lore: https://lore.kernel.org/all/20261123235154.315460-1-gahing@gahingwoo.com/
- base: next-20261120 (rockchip-iommu.c identical in v7.4-rc4)
- To: Joerg Roedel, Will Deacon, Robin Murphy, Heiko Stuebner
- Cc: Tomeu Vizoso, Daniel Drake, Sidong Yang, Anton Sovetov, Chaoyi Chen,
  iommu, linux-rockchip, linux-arm-kernel, linux-kernel
- Tested: board-logs/r429 (third part): this exact patch, kernel vmlinuz
  bbeccf35, 20/20 forced timeouts recover, 5/5 warm reboots.
- Commit message written by the user in Chinese, translated.
