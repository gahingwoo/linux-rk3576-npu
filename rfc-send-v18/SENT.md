# SENT 2026-11-24

[PATCH v18 0/8] accel/rocket: RK3576 NPU (RKNN) enablement

- cover Message-ID: <cover.1795478392.git.gahing@gahingwoo.com>
- lore: https://lore.kernel.org/all/cover.1795478392.git.gahing@gahingwoo.com/
- base: next-20261120 (909ef7a9a30f)
- rocket only; the pmdomain half was applied by Ulf (1/3 fixes
  458777762756, 2/3 next b1bff9ced657, 3/3 next adc13316e6d9). pd/ here was
  never sent.
- The known issue links the iommu fix
  <20261123235154.315460-1-gahing@gahingwoo.com>.
- Tested: board-logs/r429 (same code, messages trimmed after).
- Promise in the cover: the registers.xml change for TASK_CON_RK3576 goes
  with Mesa MR !43804 (rfc-send-v18/mesa-registers-xml-TASK_CON_RK3576.diff).
