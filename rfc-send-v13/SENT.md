# v13, what has gone out

## 2026-09-13 reply to Igor's correction of his own reports — SENT, 250

`reply-igor-0x80.eml`, Message-ID `20260912224844.1614558-1-gahing@gahingwoo.com`,
under **v12 03/14** (`...1519165-4-`), In-Reply-To his
`20260912113717.6819-1-royalnet026@gmail.com`. To Igor, Cc Tomeu,
linux-rockchip, dri-devel.

⚠ **It went under the PATCH, not the cover.** He replied to 03/14 and the
changes he asks for are that patch's commit message and tag. I had drafted it
against the cover from a guessed Message-ID; both were wrong and both were
caught by fetching the real thread. Same misplacement the v11 Tested-by had.

## What he corrected, and what it costs v12

He re-ran the 19 August protocol on v12 and found an error in **his own**
reports. His script kept the scorer output of every inference per round and
never aggregated it; his summaries scored only the one inference after the
forced autosuspend. Aggregated, the constant-0x80 result is in nearly every
run, on every arm, on all three dates.

⛔ **So the all-0x80 buffer is not a differential signal.** It is what a job
cancelled by the reset looks like from userspace: `rocket_reset()` calls
`drm_sched_stop()`, `drm_sched_start(sched, 0)` completes the detached jobs
with `-ECANCELED`, and `PREP_BO` drops the fence error. His kprobe on
`drm_sched_fence_finished()` is the direct witness: two cancellations, two
all-0x80 inferences, matched to 2 ms against a 280 ms round period.

**What he withdraws:** the 53-versus-49 bound, "19 August showed no
manifestation on either arm", and the suggestion that both statements could
stand in the commit message.
**What stands:** the provenance, 45 resets on 19 August and 102 on 25 August,
and the caveat that the protocol bounds and does not prove.

⛔ **v12 03/14 therefore states things its own witness has retracted** — "no
manifestation, oracle 48/48 throughout" and "one event in 53 differential
resets against zero in 49". That is what v13 fixes.

## What v13 owes, and this mail commits to

1. 03/14 loses the paragraph beginning "Igor also ran a differential on
   RK3588" and the one beginning "His own bound on it is the right one".
   His summary replaces them, quoted verbatim (checked character for
   character against the list copy before sending).
2. One sentence of the removed text is kept: that the protocol bounds and
   does not prove. He lists that caveat among what stands; the mail says so
   and offers to drop it.
3. `differential base` comes out of 03/14's Tested-by comment.
4. 02/14's comment becomes 04/14's. All three then read the same.
5. His 2026-09-12 message is added as a third `Link:`.
6. Nothing else changes in 02/14, 03/14 or 04/14.

⚠ **Raised back at him:** "74 today" has no referent in a commit message. A
date, or his own wording.

⚠ **Not answered, and deliberately:** his uAPI question is Tomeu's. The mail
says only what is checkable from here, that the blind spot is not his alone —
`PREP_BO` cannot tell a cancelled job from one that ran, so his protocol, ours
and the mesa one all read the same buffer.

⚠ **No credit claimed.** The 11 September mail was wrong that the numbers were
invented and that he had not measured them; it was withdrawn in the v12 cover
and this mail does not reopen it. The 0x80 mechanism is offered as
corroboration from RK3576, one paragraph, because he wrote "exactly as you
described for RK3576".

## v13 itself — PREPARED, **NOT SENT** (2026-09-14)

`v13-0000..0014`, regenerated from `v13-prep` in `~/Desktop/linux-next-v8`.
`send-v13.sh` refuses twice over, on purpose:

- the cover still carries `*** BASE HERE ***`, and
- `BASE` is still v12's `next-20260911`.

Both clear in one step: refresh the base, put the tag in the sentence.

### What is in it

All six things this file listed as owed, and one more that came out of
Igor's 2026-09-13 reply.

⚠ **The caveat is the last sentence of the QUOTE, not of the paragraph after
it.** The first cut put "It bounds; it does not prove." at the end of the
mechanism paragraph, where "it" reads as the all-0x80 buffer. Igor asked for
exactly this and said why: *"Keep the caveat, as the last sentence above, so
that 'it' has its referent once the paragraph around it is gone."* It now
reads "The protocol bounds; it does not prove." inside the quote, with a
subject of its own.

🔑 **The quote was checked character for character against the list copy**,
which is what this file promised. Normalised for wrapping, our block and his
2026-09-13 mail are identical strings.

🏁 **And the code was checked too: all 14 diff hunks are byte identical to
v12's**, md5 by md5. The cover says "byte for byte what v12 posted" and that
is a measurement, not a claim. Only 02 and 03 have a changed commit message;
the other twelve are unchanged including 04.

### Why it is held rather than sent

v11 went twelve days with zero human replies and v12 went out partly for that
reason. v12 is three days old. Sending v13 now would reset anyone mid-read for
a change that touches no code, and **Igor's correction is already on the list,
in-thread, under 03/14 itself** — so a reviewer reading that patch sees the
correction attached to it either way. The record is not silently wrong in the
meantime.

The hold is until a review arrives or about a week, whichever comes first.
Then v13 goes out with the correction AND whatever the review asks for, and
the respin reason is "the witness retracted a claim" rather than "nobody
answered".

⚠ **The base must be refreshed at send time**, not now: next-20260911 is
already three days old and the cover sentence claims the series applies to the
tag it names.

## The audit, 2026-09-14 — five false claims, and the reason to keep holding

A review of the prepared series against the lore thread found nine things. Five
changed the text; the other four are recorded here because they were checked.

⛔ **1. 04/14 carried a claim its own witness had corrected, and v13's scope
had excluded that patch.** Its body said "45 induced resets across three
cores". Igor's 2026-09-12 mail: *"all of those resets landed on core 0
(fdab0000), the other two cores being bound but idle in this single-client
protocol"*. This is the same shape as the thing v13 exists to remove, on a
patch carrying his Tested-by, and it survived because the plan above says
"Nothing else changes in 02/14, 03/14 or 04/14". **That line was written before
anybody looked.** A scope decided before the audit cannot exclude what the
audit finds.

⚠ The Tested-by comment still says "# RK3588, three cores" on all three, and
that is correct and is what he asked for: three cores were bound, the resets
landed on one. The tag says what hardware; the body said what the resets did.

⛔ **2. "Still open from v12, no reply yet" was false.** Sashiko reviewed v12 on
12 September, ten mails, with three NEW findings: a [High] on 4/14 (the
asynchronous put, with a second mechanism the v11 finding did not have --
drm_sched_start() lets the next job's resume cancel the pending autosuspend),
and on 9/14 a [High] (forcing the parent domain off at probe bypasses the child
domains' idle sequence) and a [Medium] (need_regulator hijacked to do it).
**9/14 had never been reviewed before.** There is also a [High] on 8/14 calling
rk3568-iommu an unsafe fallback, against a binding this cover calls unchanged
since v9 and Acked.

⛔ **3. The cover on disk and cover-blurb.txt had diverged.** The blurb was
edited after the splice, so the .patch still carried a paragraph that said 2/14
"already read" a comment it gains two lines later. `REGEN=1` re-splices and it
is gone; `REGEN=0` would have sent it, and `REGEN=0` also skips the marker
check. Nothing to fix in the script -- the default is right -- but the two
files can disagree and only one of them is sent.

⛔ **4. "carries the same Fixes tag as ours" (the ZhaoJinming paragraph).**
5/14 carries no Fixes tag at all. The tag ZhaoJinming's patch matches is the
one on 2/14 and 4/14. As written a maintainer concludes both sides of the
conflict are stable-marked fixes of the same commit.

⚠ **5. "46.8 s active and 14.2 s idle, which sum to the wall clock".** They sum
to 61.0 s against 60.8 s of wall clock, and r387's log says so honestly:
"60954 ms against 60800 ms". "Account for it to within 0.2 s" is what is true.

Also corrected: the census of Sashiko findings is from the v11 round and now
says so; a string attributed to 3/14 was Igor's paraphrase rather than the
patch's words; and 03/14's "with this patch and the previous one removed
together" now says which sessions were differential, because the quote under it
aggregates a 12 September session that ran two patched arms and no unpatched
one. Leaving a differential framing over a non-differential session is the
error v13 exists to remove, repeating.

### Checked and correct

The quote in 03/14 is character-identical to his 2026-09-13 mail. All fourteen
diff hunks are still byte identical to v12's after three commit messages
changed. The tag list matches the trailers one for one. The bindings are
diff-identical to the v9 patches. No em dash, en dash or non-ASCII byte
anywhere in the cover or the patches. No reverse-engineering framing.

### ⛔ AND THE HOLD IS NO LONGER JUST ETIQUETTE

The earlier reason for holding was that a respin three days after v12 resets a
reader for a no-code change. That still stands. What is new is that **v12 has
unanswered [High] review findings, one of them on a patch nobody had reviewed
before, and v13 answers none of them and changes no code.** Sending it would
put a second version on the list with the same open questions and a cover that
now names them. That is a decision about the series, not about the text, and it
is not mine to take.

## The kernel review, 2026-09-14 — and one of Sashiko's two Highs does not stand

A read of the 14 patches against the tree, independent of the text audit.

**Mechanical baseline clean.** Bisectable: the two touched subsystems build at
each of the 14 commits, and W=1 on the final tree is warning free.
dt_binding_check passes; dtbs_check is clean on five rk3576 boards and three
rk3588 ones. 09's table rewrite is value preserving across all 19 RK3576 rows
(only the intended delay=15 and the DOMAIN_RK3576_R swap). 10 is genuinely
opt-in: the only two power-domain nodes in all of arch/arm64 and arch/arm
rockchip DTS that carry `resets` are the two new RK3576 NPU ones, so every
other SoC takes the optional-get's NULL.

🏁 **9/14's [High] does not stand, and the patch now says why.** RK3588_PD_NPU
carries need_regulator with req_mask 0, exactly as RK3576_PD_NPU does, so
rockchip_pd_power(pd, false) has been running at probe on every rk3588 board
since that domain was added, with the idle request skipped because there is
none to make. Verified in tree: the macro's trailing argument is `regulator`
and the row passes `false, true`. 13 of the 49 rk3588 board files attach a
domain-supply; 36 take the dummy and the warn. If the -EINVAL half held,
rockchip_pm_domain_probe() would fail on all 49.

⚠ **4/14's [High] is right in its outcome and wrong in its mechanism**, and
the cover now says both. rpm_resume() does NOT cancel a running autosuspend
timer -- runtime.c carries a comment saying so and only deactivates the timer
when timer_autosuspends is clear. What defeats the suspend is the usage count:
rpm_check_suspend_allowed() returns -EAGAIN while it is non-zero. Both read in
the tree. The scope is narrower than the finding suggests, because
drm_sched_start() completes the detached jobs with -ECANCELED rather than
re-running them; the gap needs a client with a second job queued or a resubmit
inside 50 ms. Incomplete coverage, not a regression.

⛔ **And a pre-existing bug came out of checking 3/14's own reasoning.**
rocket_core_fini() puts and NULLs core->iommu_group BEFORE rocket_job_fini(),
which is what cancels the timeout worker via drm_sched_fini(). A timeout in
that window reaches rocket_reset()'s
`iommu_detach_group(NULL, core->iommu_group)` on the stored pointer. Verified
by reading all three functions. It is in the cover's pre-existing list for
Tomeu, with the note that 3/14 adds a synchronize_irq() into the same window.

⚠ **Patch 05's iommu_group leak is unchanged by 05**, as the cover already
says -- and the fix is a one word change: four lines away, rocket_reset() does
the same detach using the stored core->iommu_group with no extra get, while
the moved line still does iommu_group_get(core->dev).

### ⛔ A git mistake worth writing down, because it cost the branch

Amending 09 was done as

    git checkout -B v13-tmp $NINE && git commit --amend && \
        git cherry-pick $NINE..v13-prep | tail -1 && \
        git branch -f v13-prep v13-tmp

**A pipeline's exit status is the LAST command's.** The cherry-pick hit a
conflict, `tail` succeeded, `&&` carried on, and `git branch -f` moved
v13-prep onto a branch holding nine patches instead of fourteen. Nothing was
lost -- the good state was in the reflog, restored from e5cb712e6 -- but for a
few minutes the branch was silently short five patches while the on-disk
patches still showed the right content.

🔑 It also produced a WRONG DIAGNOSIS: a check for an earlier fix was run
against a sha read off the truncated branch, came back 0, and was reported as
"the amend did not land". It had landed. **After a git operation fails, re-read
the shas before checking anything against them.** Never put a pipe in an `&&`
chain that ends in a force-update.

## 2026-09-14 late — both of Sashiko's remaining findings fall, and my own numbers were wrong

**8/14 [High] does not stand.** The premise is right: before upstream
`841363ebb508` ("iommu/rockchip: Take all DT clocks", in Linus's tree since
v7.3-rc1) the driver took only `aclk` and `iface` by name. But the conclusion
does not follow, for three independent reasons.

- **There is no register access on that path.** Every MMIO site in
  rockchip-iommu.c is behind `pm_runtime_get_if_in_use()`, and on an old
  kernel the device never resumes: probe touches no register, there is no
  `pm_runtime_set_active()`, and the only thing that could wake it is the
  device link from its master. The master compatible
  `rockchip,rk3576-rknn-core` exists nowhere upstream; it is added by 12/14 of
  this series.
- **The failure mode named is wrong for this block.** `841363ebb508`'s own
  message says writes to DTE_ADDR are SILENTLY DROPPED until the extra clocks
  run, and reads work. Not a hang, not a fault.
- **DT ABI points the other way.** The documented guarantee is that a newer
  kernel will not break on an older device tree. Old kernel with new DT is not
  a combination the ABI promises.

⛔ **And the suggested fix would destroy the series.** `rk_iommu_dt_ids[]` has
exactly two entries, `rockchip,iommu` and `rockchip,rk3568-iommu`;
`rockchip,rk3576-iommu` and `rockchip,rk3588-iommu` already bind only through
the fallback. Drop it and the NPU has no IOMMU and 12/14 through 14/14 are
dead. 121 in-tree bindings have the same shape (a fallback plus a
compatible-gated clock count); `arm,mali-bifrost` is the closest precedent.

**9/14 [Medium] does not stand either.** `need_regulator` exists only in
pm-domains.c and has exactly two documented meanings there, both pre-existing;
the probe-time power-off is the one the base tree's own comment describes. The
warning is a one line `dev_warn` from the regulator core, and it fires in
`->power_on`, NOT at the probe-time power-off.

⛔⛔ **BUT MY OWN PARAGRAPH IN 09/14 HAD THE NUMBERS WRONG, and I wrote it
tonight.** I said "thirteen of the forty-nine rk3588 board files give that
domain a domain-supply; the other thirty-six take the dummy regulator and the
warn." Thirteen was a count of SOURCE FILES containing the property, including
.dtsi, against forty-nine BOARD FILES: two different units. Resolving the
includes properly, and reproduced independently:

    21  enable an NPU core and declare the supply
     2  enable it with no supply, and warn today: quartzpro64, youyeetoo-yy3588
    26  do not enable an NPU core, so ->power_on never runs and nothing warns

The same error was in the paragraph the patch already had about rk3576: it
said twelve boards "take a dummy regulator and a dev_warn", when those twelve
never reach a first power-on at all. Only rock-4d enables a core, and it is
the one that declares the supply. Both halves are corrected.

🔑 This is the second time in one day that a number I put in outward text was
derived from a `grep -c` over files rather than over the thing being counted.
**Counting files is not counting boards.**
