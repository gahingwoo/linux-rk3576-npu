# WITHDRAWN. This fix is already on the list, and it is not ours.

    WITHDRAWN-do-not-send-0001-iommu-group-leak.patch.txt

DO NOT SEND. The file is kept only so this directory records what happened; the
`.patch` suffix was removed so it cannot be picked up by a send script.

## What I got wrong

I found that `rocket_job_handle_irq()` retires a job with

    iommu_detach_group(NULL, iommu_group_get(core->dev));

which leaks one IOMMU group reference per job, wrote a one-line fix with
`Fixes: 0810d5ad88a1`, and carved it out of `attach-once/0001` as something that
could go to stable on its own.

Then I searched lore, which is what I should have done first.

## Who actually owns it

**ZhaoJinming <zhaojinming@uniontech.com>** posted it in June 2026 and carried
it through six revisions:

    [PATCH v3 2/2] accel/rocket: Fix iommu_group leak and unsafe IRQ register access
    2026-06-09 .. [PATCH v6 2/2] 2026-06-10
    https://lore.kernel.org/all/20260610060132.3239648-2-zhaojinming@uniontech.com/

The 1/2 of that series LANDED as `9b2dedadf6a9 ("accel/rocket: Fix error path
handling in rocket_job_run()")`, 2026-07-04. The 2/2 — the group leak — did not,
which is why linux-next 20260911 still has the bug.

**Igor Paunovic** has been trying to unstick it since July, and wrote again on
**2026-09-09**, six days before I wrote my duplicate, offering ZhaoJinming
either of two things: respin the leak fix alone as a standalone v7 and he tests
it on RK3588 the same day with a Tested-by, or he posts it on ZhaoJinming's
behalf with ZhaoJinming as author and his own Signed-off-by only as the person
posting. "The fix is yours; I do not want to take it over, only to stop it from
being stuck."

A third copy of that one line, from us, would step on two people who are
actively coordinating on it.

## What is actually useful here, and it is the user's call

A **Tested-by on RK3576** when the standalone lands. Nobody in that thread has
RK3576 hardware; Igor's offer is RK3588. That is the one thing this project can
add that the thread does not already have, and it is an outward send, so it
waits for the user.

## The lesson, again

"Silence of one thread is not absence" — and neither is the absence of a fix in
the tree. `linux-next` not carrying it meant nobody had LANDED it, which is a
different statement from nobody having SENT it. Search before writing, not
after. Two searches would have cost five minutes: `s:"accel/rocket" AND s:"leak"`
on lore finds it on the first page.

## Two corrections to the above, and both are mine

**The review agent was right about Chaoyi Chen and I checked the wrong patch.**
I looked at `[PATCH 1/4] accel/rocket: Fix the IOMMU domain leak in
rocket_ioctl_create_bo`, which is a different bug, and concluded the
attribution was wrong. It is `[PATCH 3/4] accel/rocket: Fix the extra
iommu_group_get call in rocket_job_handle_irq`, 2026-08-14, same series, and it
is exactly this line. So there are now three copies in play: ZhaoJinming's from
June (bundled with runtime PM guards), Chaoyi Chen's standalone from August,
and the one withdrawn here.

**And this project had already worked all of that out, on 2026-09-14.**
`reply-chaoyi/reply-chaoyi-fixes-tag.eml` says it in as many words: it corrects
Chaoyi's `Fixes:` tag to 0810d5ad88a1, names ZhaoJinming's June copy, names
Igor's two offers, and says "I have the same one line change on a branch here
and am not posting it. Yours came first as a standalone patch, and a third copy
of a one liner would be noise."

So tonight did not find a duplicate. It re-derived a decision that was already
made and written down, because it did not read `reply-chaoyi/` first. A closed
question does not look closed from the outside; it looks like an open one
nobody has touched.
