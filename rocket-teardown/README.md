# rocket teardown: one patch to send, one that is already on the list twice

Branch `rocket-teardown` in `~/Desktop/linux-next-v8`, on next-20260911, which
was the series base when this was written; v13 went out on next-20260914. It is
NOT on `v13-prep`: both patches stand alone against mainline.

**NOT SENT. Neither patch has gone anywhere.** What HAS gone out is a
description: 0001's bug is in v13's cover (2026-09-15) as a pre-existing finding
for Tomeu Vizoso, named with the reasoning and without a patch, because 3/14 adds
a `synchronize_irq()` into the same window.

## 0001 — cancel the timeout worker before dropping the IOMMU group

Real, verified end to end, and **nobody has posted a patch for it**. lore
searched for `b:"rocket_core_fini"`, `b:"rocket_job_fini"` since June and every
`s:"accel/rocket"` subject this year. v13's cover describes the bug but carries
no fix for it.

`rocket_core_fini()` clears `core->iommu_group` and only then calls
`rocket_job_fini()`, which is what cancels the timeout worker through
`drm_sched_fini()`. A worker that reaches `rocket_reset()` after the store
takes `iommu_detach_group(NULL, NULL)` and `mutex_lock()` on it.

The failing window is wider than "a timer fires between two statements".
`drm_sched_stop()` sits in front of the detach doing two `cancel_work_sync()`s
and an uninterruptible `dma_fence_wait()` on a job still on the hardware, so a
worker parked there is then waited for by the very
`cancel_delayed_work_sync()` that was supposed to have stopped it, and takes
the NULL on the way out. Trigger: sysfs unbind of a core with a job in flight.

**Two things I had wrong when I briefed this, both corrected by checking:**
- **It is a NULL dereference, not a use after free.** `iommu_group_add_device()`
  holds its own reference for `dev->iommu_group`, dropped only on device
  removal, so the put takes the count 2->1 and frees nothing.
- **Module unload is not a second route.** `rocket_open()` does
  `try_module_get(THIS_MODULE)` per open file, so `rmmod` cannot run with a
  client attached. Sysfs unbind has no such guard.
- `cancel_work_sync(&core->reset.work)` is not the live path either:
  `core->reset.work` has no `queue_work()` site in tree.

## 0002 — the iommu_group leak. DO NOT SEND THIS.

The one line fix is correct and it is **already on the list twice**:

- Chaoyi Chen, `[PATCH 3/4] accel/rocket: Fix the extra iommu_group_get call
  in rocket_job_handle_irq`, 2026-08-14, standalone, still unapplied as of
  2026-09-16 (linux-next carries no accel/rocket commit newer than 2026-08-11)
  https://lore.kernel.org/all/20260814022453.437-4-kernel@airkyi.com/
- ZhaoJinming, `[PATCH v3..v6 2/2]`, 2026-06, bundled with runtime-PM guards
  around the IRQ handler, which is what stalled it

Igor Paunovic offered on 2026-09-09 to test a standalone respin or post it
himself with Zhao as author. Still unanswered on 2026-09-16.

The file here is **Chaoyi's patch carried**, with his From: and his SoB, kept
only so the branch builds and is testable. A third posting of a one line fix
would be noise.

**What IS worth sending is a reply to his thread: his `Fixes:` tag is
wrong.** He cites `658ebeac3351 ("accel/rocket: Add IOCTL for BO creation")`,
which touches Makefile, rocket_drv.[ch], rocket_gem.[ch] and the uapi header
and does not touch `rocket_job.c` at all. Both that line and
`rocket_job_handle_irq()` came from `0810d5ad88a1`. A corrected tag plus a
Tested-by from this board is worth more than another copy, and it also settles
the conflict v13's cover raises with Tomeu, which is now on the list.

## A window neither patch closes

A completion interrupt arriving after `rocket_core_fini()` returns (the devm
IRQ is released by devres only once `remove()` has returned) reads
`core->iommu_group`, which fini has just cleared. 0002 changes that window's
symptom from a leaked reference to a NULL dereference. It is already broken in
the same breath for other reasons: it signals a fence and puts a runtime PM
reference for a job the scheduler has stopped tracking. Closing it means
quiescing the hardware in `rocket_core_fini()`, and `devm_free_irq()` there is
not obviously right on an IRQF_SHARED line the device may still be asserting.
That deserves its own patch.

## Build

Native aarch64, `CONFIG_DRM_ACCEL_ROCKET=y`. `make W=1 drivers/accel/rocket/`
is warning free patched and at the base, so no new warnings.
`checkpatch.pl --strict` is 0 errors 0 checks on both; the one warning each is
`Unknown commit id`, an artifact of the depth-15 shallow clone.
