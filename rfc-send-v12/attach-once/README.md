# attach-once: two rocket patches, delivered as a whole kernel

`0001` keeps the IOMMU domain attached across jobs (rk_iommu's attach is a
FORCE_RESET and five polls, twice a job). `0002` handles the completion in
the hardirq. Both untested on hardware as of 2026-09-02.

**Why a whole kernel and not a module:** `kernel/npu.fragment` builds rocket
in (`CONFIG_DRM_ACCEL_ROCKET=y`) because a module probes after the
late_initcall that cuts vdd_npu_s0. There is no rocket.ko on the board to
swap. The modules that were here earlier are gone for that reason.

`package-kernel.sh` turns a full in-tree build with the board's own config
(`kernel/base.config` + `kernel/npu.fragment`, `LOCALVERSION_AUTO` off so the
release string is exactly `7.2.0-rc5-next-20260730`) into the layout
charsiu-install takes: Image, dtb, modules tarball, SHA256SUMS. It is
published as a GitHub PRE-release, which `releases/latest` never returns,
and installed on purpose with `CHARSIU_KERNEL_TAG=<tag>`.
`board-kernel-revert.sh` puts the previous kernel back.
