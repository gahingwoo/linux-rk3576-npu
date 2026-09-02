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

## 2026-09-02 evening: rebased onto v11

The old LNEXT tree was aligned with v9 and lacks v11-0009's regulator
argument for the RK3576 domains, so every Image built from it -- with or
without these patches, with either toolchain -- dies on the first NPU job:
the dtb hands vdd_npu_s0 to the pm-domain driver and that driver never
enables it. The two patches here are now exported from the `v11-attach`
branch (linux-next 20260730 + v11 + the ROCK 4D second core), where they
apply cleanly. Kernels: `kernel-7.2.0-rc5-next-20260730-v11-control` and
`kernel-7.2.0-rc5-next-20260730-attach-once-v11`, both pre-releases, both
buildroot gcc 12.4.0.
