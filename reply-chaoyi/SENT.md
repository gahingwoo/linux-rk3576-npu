# reply to Chaoyi Chen: his Fixes: tag names the wrong commit

**NOT SENT. Nothing here has gone anywhere.** There is no send script and
none is to be written. Not committed, not pushed.

File: `reply-chaoyi-fixes-tag.eml`

## The claim the mail makes, and how each half was checked

**The tag is wrong.** Checked against git.kernel.org, not against memory.

- `658ebeac3351 ("accel/rocket: Add IOCTL for BO creation")`, full SHA
  `658ebeac33517bd3169d4b65ed801e9065d0211a`, touches exactly six files:
  `drivers/accel/rocket/{Makefile,rocket_drv.c,rocket_drv.h,rocket_gem.c,rocket_gem.h}`
  and `include/uapi/drm/rocket_accel.h`. The string `rocket_job` does not
  appear anywhere in its diff.
- `0810d5ad88a1 ("accel/rocket: Add job submission IOCTL")`, full SHA
  `0810d5ad88a18f1e6d549853a388ad0316f74e36`, **adds `rocket_job.c`**, and
  its diff adds `rocket_job_handle_irq()` (+584), the leaking
  `iommu_detach_group(NULL, iommu_group_get(core->dev))` (+598) and
  `rocket_reset()`'s `iommu_detach_group(NULL, core->iommu_group)` (+622).
- **`0810d5ad88a1`'s parent is `658ebeac33517bd3169d4b65ed801e9065d0211a`.**
  Read off the cgit commit page. So the cited commit is the immediate parent
  of the one that introduced the line, which is what the mail says.
- `cgit /log/drivers/accel/rocket/rocket_job.c` on mainline lists
  `0810d5ad88a1` as the file's first commit and no later commit that touches
  the line.

**It is still unfixed.** The mail says "still there in mainline and in
linux-next today" (2026-09-14). Checked by fetching the plain file from both
trees: `torvalds/linux.git` and `next/linux-next.git` both have
`iommu_detach_group(NULL, iommu_group_get(core->dev));` at line 358 and
`iommu_detach_group(NULL, core->iommu_group);` at line 382. linux-next
carries drm-misc-next, so that covers the "already queued somewhere" case.

**Zhao's copy carries the right tag.** `[PATCH v6 2/2]` of 2026-06-10
carries `Fixes: 0810d5ad88a1 ("accel/rocket: Add job submission IOCTL")` and
`Cc: stable@vger.kernel.org`. Read from the list copy, not inferred. His
1/2 landed (`accel/rocket: Fix error path handling in rocket_job_run()`,
in the rocket_job.c log dated 2026-07-04); the 2/2 did not.

**Nobody answered Igor.** His 2026-07-29 and 2026-09-09 mails are messages
24 and 25 of that thread and the thread ends there. Zhao's last message in
it is 2026-06-12, on 1/2. So "no answer to either so far" is a statement
about the public archive as of today.

**No Tested-by.** The mail claims exactly two things about this board and
nothing more: the patch is carried here on `next-20260911` and it builds
clean.

- Carried: branch `rocket-teardown` in `~/Desktop/linux-next-v8`, commit
  `3ea5d4174`, whose grandparent is `68142f986` ("Add linux-next specific
  files for 20260911").
- Builds: verified in this session, not taken from the earlier README.
  A throwaway worktree at `68142f986` with **only** Chaoyi's patch applied,
  `make O=... -j6 W=1 drivers/accel/rocket/`, exit 0, no warnings. Native
  aarch64, the tree's own `.config` (`CONFIG_DRM_ACCEL_ROCKET=y`). The
  worktree was removed afterwards; `linux-next-v8` is back on `v13-prep`
  and clean.
- **Not booted.** No kernel with this patch has run on the board, so no
  tag is offered. The mail offers to run it on a respin instead.

**The conflict.** v12 05/14 "accel/rocket: factor the completion tail out of
the IRQ handler" is public at
`20260912065053.1519165-6-gahing@gahingwoo.com` (subject confirmed by
fetching it). It moves that line unchanged into `rocket_job_next_locked()`.
The posted v12 cover raises the conflict against **Zhao's** patch only:
"ZhaoJinming's ... changes the same line, is marked for stable, and carries
the same Fixes tag as ours. Whichever lands first the other conflicts; say
which you would rather take." The mail says so and says it should have named
Chaoyi's too. It does **not** claim a reason for the omission; why it was
not named is not checkable from here.

## Headers

Scraped from the real message, not invented.

- `In-Reply-To: <20260814022453.437-4-kernel@airkyi.com>` (his 3/4).
- `References:` the cover `<20260814022453.437-1-kernel@airkyi.com>` then the
  patch. His 3/4's own `In-Reply-To` is that cover.
- The series went out **twice**; lore shows "multiple messages have this
  Message-ID" for both copies, with identical headers. The Message-ID used
  here is the one both copies carry.
- To/Cc are taken from his 3/4's own header block: To Tomeu Vizoso, Oded
  Gabbay, Heiko Stuebner, Jeff Hugo; Cc linux-kernel, dri-devel,
  linux-rockchip, linux-arm-kernel. Both of his addresses are in To.
- **Added beyond that thread:** ZhaoJinming and Igor Paunovic. The mail
  discusses Zhao's patch and Igor's standing offer, so both should see it.
  sashiko-bot is not Cc'd.
- No `Date:` or `Message-ID:` header; `git send-email` generates both. It
  also reads To/Cc/Subject/In-Reply-To from the file, so no flags are needed.

## Deliberately not in the mail

- **sashiko-bot's [High] on his 3/4**, that caching the pointer introduces a
  NULL dereference during teardown. It is not baseless, and our own
  `rocket-teardown/README.md` agrees the patch changes that window's symptom
  from a leaked reference to a NULL dereference, so it could not have been
  waved away in one line. It belongs with the teardown patch (0001), which
  is a separate mail, not with a tag correction.
- **0001** ("cancel the timeout worker before dropping the IOMMU group").
  Still unposted and unmentioned here.
- **The downstream RK3576 kernel.** `kernel/0001-rk3576-...patch` makes the
  same change to that line (and also passes `job->domain->domain` instead of
  NULL), but no local tree reproduces what the board actually boots, so the
  "it has run here for months" argument cannot be checked and is not made.

## House rules

ASCII only, checked with `grep -P '[^\x00-\x7F]'` and the unicode cleaner's
`--detect` (clean). No em or en dashes. Body lines are at or under 72
columns except the three reference URLs, which are unbreakable.
