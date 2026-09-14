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
