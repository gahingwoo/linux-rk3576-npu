# One patch, held: the IOMMU group reference rocket leaks per job

    0001-accel-rocket-don-t-leak-an-IOMMU-group-reference-per.patch

NOT SENT. Nothing in this directory goes anywhere without the user saying so.

## What it is

`rocket_job_handle_irq()` retires a job with

    iommu_detach_group(NULL, iommu_group_get(core->dev));

`iommu_group_get()` returns the group with `kobject_get(group->devices_kobj)`.
`iommu_detach_group()` takes the group mutex, calls
`__iommu_group_set_core_domain()`, and returns -- it does not put anything. So
one group reference is leaked for every job that retires, the group's kobject
can never reach zero, and `rocket_core_fini()`'s own `iommu_group_put()` stops
releasing it.

The core already holds the group for its whole life: `rocket_core_init()` takes
it into `core->iommu_group` and `rocket_core_fini()` puts it. The other two
call sites in the file use that member -- the attach in `rocket_job_run()` and
the detach in `rocket_reset()`. This one is the odd one out, and the fix is to
use the member there too.

    Fixes: 0810d5ad88a1 ("accel/rocket: Add job submission IOCTL")

Confirmed by fetching that commit: it added all three call sites in one patch,
two using `core->iommu_group` and one not.

## Why it is its own patch

This is NOT a new finding. `rfc-send-v12/attach-once/0001` has carried the same
observation in its commit message since 2026-09-02, because attach-once deletes
the whole per-job detach and the leak goes with it.

Carving it out is the point. attach-once is a performance change that touches
the job lifetime, adds a field to `struct rocket_core` and has to argue about
suspend and reset; a maintainer can reasonably sit on it. This is one line with
a `Fixes:` tag that stands on its own and can go to stable. Sending the small
one first is also how the reviewer of the big one gets a smaller diff.

If both go, this comes first and attach-once rebases on top.

## Base

`68142f986` -- linux-next 20260911, the same base as `v13-prep`. It does NOT
touch v13-prep, which is held unsent and unchanged. The fix applies to the
upstream function `rocket_job_handle_irq()`; on top of our series the same line
lives in `rocket_job_next_locked()`, moved there verbatim by
`33f35c4b8 ("accel/rocket: factor the completion tail out of the IRQ handler")`,
whose "no functional change" is accurate.

## Not built

The kernel was not rebuilt for this. `core->iommu_group` is `struct iommu_group *`
at `rocket_core.h:51` and is dereferenced the same way two lines away in the
same file, so the change is a substitution of an expression for an equal one.
That is an argument, not a build. Say so if it is ever sent untested.
