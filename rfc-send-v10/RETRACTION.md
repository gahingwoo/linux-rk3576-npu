# RETRACTION: what v10 said about Igor Paunovic's differential run

Resolved 2026-09-12 by reading his own two messages on lore. **Nothing in this
directory's prose about a reproduced race is true, and the count is invented.**

The files in here are left AS SENT. They are the record of what went out; the
point of this note is that the record is wrong, not that it should be edited
into looking right.

## What v10 claimed

`v10-0000-cover-letter.patch` (posted), `cover-blurb.txt`, and
`CHANGELOG-DRAFT.md`:

> A job that signals completion while its output buffer is never written is the
> silent form of the race 1/13 and 2/13 close, and across 102 induced resets in
> nine runs that day it appeared only on the arm without them.

`reply-igor-sizee-oc64.eml`, sent to Igor:

> The run that signalled success with an output buffer that was never written,
> all 48 channels 0x80 and nothing in the log, is the clearest statement of
> what these two patches close that anyone has produced, including me.

## What Igor actually reported

`20260819073530.6087-1-royalnet026@gmail.com`, his differential, in full:

```
              loglevel 8   loglevel 4   recovery   oracle
  with 1+2/12     12            8        all clean  48/48 both passes
  without         12           13        all clean  48/48 both passes
```

12 + 8 + 12 + 13 = **45**, which is his own figure: "all 45 of my resets hit a
healthy block crossing a 2 ms timeout, and the domain dropped every single
time, on both kernels."

And, in the same message:

> The race itself did not manifest in the 45 resets on either kernel.
> Timeouts are easy to induce; a completion racing the reset inside a
> microseconds-wide window is not, so the justification for the pair remains
> the source analysis.

His oracle is 48/48 on BOTH arms. No inference produced a wrong output on
either kernel.

## Three faults fused into one sentence

- **the count** -- 102 across nine runs is invented; his is 45 across two
  passes per kernel.
- **the conclusion** -- INVERTED. He wrote that the race did not manifest and
  that he could not reproduce ours; v10 says it appeared on the unpatched arm.
- **the signature** -- "all 48 channels 0x80" is OURS, from `FINDINGS.md`: on
  RK3576 a fresh shmem BO is zeroed and teflon's readback adds 0x80, so an
  output buffer that was never written comes back as a uniform 128. That entry
  marks the signature as a trap that had already cost this project one
  retraction. It was carried across to an RK3588 run that never reported it.

## What is correct and can be quoted

`v12-0004-accel-rocket-let-the-core-suspend-after-a-reset.patch` (also v9, v10,
v11), which is what ships:

> Igor Paunovic ran the differential on RK3588: 45 induced resets across three
> cores, with and without the two preceding patches, and the domain dropped
> every single time with no MMU message on either kernel. So this is not
> rocket-wide.

That matches him line for line, including the limit he was careful to state
himself. **It is a bounding result, not a reproduction**, and it is the only
form of his numbers that may appear in the paper or in any future cover.

v11 and v12 carry no version of the false claim; they kept only his two
Tested-by lines, whose conditions are his verbatim.

## ⚠ Open, and it is not a tree question

The v10 cover is on lore and the mail reached Igor. He travelled from
2026-08-20 and never replied to it. Whether to send a correction is not
something this file can settle.
