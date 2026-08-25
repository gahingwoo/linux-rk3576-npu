# Upstream fixes that landed after v7.2

**None of these are ours.** They are other people's commits, already in
linux-next and heading for 7.3, cherry-picked here so the RK3576 NPU series can
be built on a **released** mainline kernel rather than on a linux-next tag.

v7.2 is the newest mainline release and it already carries `drivers/accel/rocket`
(for RK3588). It does not carry these four, and the v9 series was written on top
of a tree that has them, so without them patch 4 fails on `rocket_job.c` and
patch 8 fails on `pm-domains.c`. Measured, not assumed.

| | commit | author | what |
|---|---|---|---|
| 0001 | `70e6a33d68a9` | upstream | rocket: initialize job domain before cleanup paths |
| 0002 | `a85402bff218` | upstream | rocket: fix NULL deref and integer overflow in `rocket_job_push()` |
| 0003 | `9b2dedadf6a9` | upstream | rocket: fix error path handling in `rocket_job_run()` |
| 0004 | `c8e1c83f9ad7` | Midgy BALON | pmdomain/rockchip: add a regulator to the RK3568 NPU power domain |

0004 is the one that introduces `DOMAIN_M_R` and the `need_regulator` field, which
is what v9's *"pmdomain/rockchip: add optional per-domain power-on settle delay"*
extends. The first three are the `pm_runtime_resume_and_get` error unwinding and
the overflow hardening in the job path.

**When 7.3 is released, delete this directory and move the base tag** — every one
of these is upstream, so the only reason they are here is that 7.2 shipped first.

## Verified 2026-08-25

On a clean `v7.2` checkout, in this order:

    kernel/backport-7.2/*.patch     4, all applied
    rfc-send-v9/prereq/*.patch      1 (Igor Paunovic's clocks-by-name, which the
                                    v9 cover letter declares as its prerequisite)
    rfc-send-v9/v9-00[01-13]*.patch 13, all applied

then `drivers/accel/rocket/` and `drivers/pmdomain/rockchip/` compile with no
errors and no warnings.

⚠ `CONFIG_DRM_ACCEL_ROCKET` cannot be `y` while `CONFIG_DRM` is `m` — it selects
`DRM_SCHED` and `DRM_GEM_SHMEM_HELPER`. Enable `DRM` first. On this rootfs a
module is never loaded (no udev, no mdev), so `m` means the NPU does not work.
