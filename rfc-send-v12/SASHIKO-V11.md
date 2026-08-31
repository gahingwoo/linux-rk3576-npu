# Sashiko's review of v11, adjudicated

Sashiko reviewed all nine mails of v11 on 2026-08-31. That it ran at all is the
point of v11: v9 and v10 named Igor Paunovic's clock patch with a
`prerequisite-patch-id:` trailer, which the bot cannot follow, so v11 carries it
as 1/14 and the whole series was reviewable.

Almost everything it found is labelled **pre-existing** and belongs to the
upstream rocket driver, not to this series. The repeats are worth reporting to
Tomeu on their own:

| finding | mails |
|---|---|
| `iommu_group` reference leak in the job completion path | 9 of 9 |
| shared IRQ handler touches registers without checking PM state | most |
| runtime suspend lacks `synchronize_irq()` | 3 |
| `num_cores` used as both array length and probe index | 2 |
| devres leak of `rdev` on probe deferral | 2 |

Four findings are attributed to this series. Verdicts below.

## 1. 11/14 -- no NULL check on `of_device_get_match_data()` -- VALID, fixed

`core->soc` is dereferenced with no check in eight places (`->num_resets`,
`->num_clks`, `->multi_power_domain`, `->task_con_16bit`), the first of them
two statements after the assignment. A platform device that bound by name
rather than by compatible has no match data.

Sashiko calls it a "guaranteed kernel panic on manual sysfs bind", which
overstates it -- an unbind and rebind of a device that has an OF node still
matches and still gets its data. But the check is one line and upstream will
ask for it. Fixed.

## 2. 03/14 -- `-EINVAL` treated as inactive -- VALID, fixed, and worse than "Medium"

The code tested `pm_runtime_get_if_active(core->dev) > 0`. The kernel documents
three answers, not two:

    Increment the runtime PM usage counter of @dev if its runtime PM status is
    %RPM_ACTIVE, in which case it returns 1. If the device is in a different
    state, 0 is returned. -EINVAL is returned if runtime PM is disabled for the
    device, in which case also the usage_count will remain unmodified.

`drivers/accel/rocket/Kconfig` has no `depends on PM` and no `select PM`, and
the driver reaches its PM callbacks through `RUNTIME_PM_OPS`, which compiles
away when `CONFIG_PM=n`. In that configuration `pm_runtime_get_if_active()` is
the stub that returns `-EINVAL` unconditionally, so `> 0` is never true and the
INTERRUPT_MASK write **never happens** -- the protection 03/14 exists to add is
silently absent on every `CONFIG_PM=n` build. And that is the one configuration
where the domain cannot be down, so the write could not have faulted.

Fixed by testing `!= 0` and putting the reference only when one was taken,
since `-EINVAL` takes none.

## 3. 04/14 -- `pm_runtime_put_autosuspend()` is asynchronous -- OPEN, needs the board

This one attacks the patch's mechanism rather than its wording, and the code
around it makes the case stronger than the bot did:

- the autosuspend delay is **50 ms**, set in `rocket_core_init()` and chosen
  deliberately ("~3 frames at 60Hz") to keep the device powered through a media
  pipeline;
- `rocket_reset()` calls `drm_sched_start()` at its end, so the scheduler
  resubmits immediately;
- a resubmit takes a PM reference and cancels the pending autosuspend.

So on any workload whose gap between submits is under 50 ms, the core does not
suspend after a reset. That matters because 04/14 and 10/14 are a pair: 04/14
lets the domain power off, and 10/14 pulses the domain's resets when it powers
back **on**. If the domain never cycles, 10/14 never fires. `rocket_core_reset()`
still asserts the *core's* own resets either way, so the question is whether the
core reset alone is enough on RK3576 -- and this project has recorded that the
block stays dead after a timeout, which is what that would look like.

⚠ Not fixed here. A synchronous put inside `scoped_guard(mutex, &core->job_lock)`
is not obviously safe, and the claim is empirical. See `sashiko-3-suspend.sh`.

## 4. 03/14 -- lockless INTERRUPT_MASK race -- REFUTED

Sashiko: "Lockless modification of INTERRUPT_MASK in rocket_reset() races with
concurrent task submission in the IRQ handler, potentially leaving interrupts
enabled."

The re-arm path is real -- the threaded handler calls
`rocket_job_next_locked()`, which calls `rocket_job_hw_submit()`, which writes
`INTERRUPT_MASK` -- but it cannot run in this window:

    static void rocket_job_hw_submit(struct rocket_core *core, ...)
    {
            /* Don't queue the job if a reset is in progress */
            if (atomic_read(&core->reset.pending))
                    return;

That guard is upstream's, it is the first statement in the function, and it
returns before any register write and before `next_task_idx++`.
`rocket_job_timedout()` sets `reset.pending` to 1 *before* calling
`rocket_reset()`, `rocket_reset()` returns immediately unless it is set, and it
is not cleared until after `rocket_core_reset()`. So across the entire window --
the mask write, `synchronize_irq()`, the scoped guard and the core reset -- the
only submit-path writer of INTERRUPT_MASK is disabled.

The guard is three frames from the write, in a function the patch does not
touch, which is a fair thing for a reviewer to miss.
