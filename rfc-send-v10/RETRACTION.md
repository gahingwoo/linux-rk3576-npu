# What v10 said about Igor Paunovic's differential: it was RIGHT

⛔⛔ **This file said the opposite on 2026-09-12 and that was wrong. The error
was mine, it went out on a public list, and it has been withdrawn.** What
follows is the corrected record.

## The claim v10 made

`v10-0000-cover-letter.patch` (posted 2026-08-31), `cover-blurb.txt`, and
`CHANGELOG-DRAFT.md`:

> A job that signals completion while its output buffer is never written is the
> silent form of the race 1/13 and 2/13 close, and across 102 induced resets in
> nine runs that day it appeared only on the arm without them.

## It is a faithful quotation of Igor, six days earlier

`CAEWPSH5mxTbUkNouxm6yecMZYvDowquhvYvhaXQ8HoMtHD5U1g@mail.gmail.com`, Igor
Paunovic, **2026-08-25**, Re: `[PATCH v9 02/13]`, his own words:

> One of the extra runs came back with something I had not seen before: the
> inference after the forced autosuspend "succeeded" but returned a constant
> buffer - all 48 output channels uniformly 128 (0x80), which is not the output
> zero point of this model, while the CPU reference varies normally. Zero
> kernel messages, zero lockdep hits, nothing on the serial console. A job that
> signals completion while its output buffer is never written is exactly the
> silent flavour of the race these two patches close, and in 102 induced resets
> across nine runs today it appeared only on the arm that does not carry them.

Both the count and the 0x80 are his, measured on his RK3588.

## Two runs, not one, and they do not conflict

| | 2026-08-19, against the v8 pair | 2026-08-25, the v9 re-run |
|---|---|---|
| message | `20260819073530.6087-1-royalnet026@gmail.com` | `CAEWPSH5mxTb...@mail.gmail.com` |
| resets | 45, two passes per kernel | 102 across nine runs |
| outcome | oracle 48/48 on both arms | one extra run on the UNPATCHED arm returned all-0x80 |
| his words | "The race itself did not manifest in the 45 resets on either kernel" | "it appeared only on the arm that does not carry them" |

Different sessions, different arms, different days. Neither statement is in
tension with the other.

## ⛔ What I got wrong, and how

On 2026-09-12 I pulled the 2026-08-19 thread, found only the 45-reset run in
it, and concluded from that single thread that the 102 had been invented and
that the 0x80 signature had been borrowed from our own RK3576 work. I then
wrote it up here and sent a public correction telling Igor, in front of
linux-rockchip and dri-devel, that none of it was what he reported.

**I read one thread and treated its silence as an absence.** The lore search
that settles it takes one command (`b:"102 induced resets"` returns his message
as the earliest hit, six days before our cover) and I did not run it. The tree
already carries this exact lesson about a truncated `find` being read as an
exhaustive one; the tool changed and the mistake did not.

⚠ And the rest of the reasoning was built to fit. `FINDINGS.md` does record
that on RK3576 an unwritten buffer reads back as a uniform 128, which is true
and is OUR result. That made "he borrowed our signature" feel explanatory. Two
platforms reading 0x80 for an unwritten buffer is not a coincidence needing an
explanation; a zeroed BO plus an unsigned readback offset gives 128 on either
one.

## The mails

- **2026-09-11** `<20260911122832.1364839-1-gahing@gahingwoo.com>`, the wrong
  correction, sent to Igor, Tomeu and both lists.
- **2026-09-11 19:29Z** `<20260911192833.105634-1-royalnet026@gmail.com>`, Igor
  setting it straight himself, the same day: "both sets of numbers are mine,
  from two different days", "the signature is shared, not carried over", and
  "If you respin, both statements can stand next to each other."
- **the withdrawal rides in the v12 cover**, not as a third mail on the thread.
  See `rfc-send-v12/cover-blurb.txt`, the paragraph before "The tags:".

## What Igor asked for, and it is not yet in the series

His reply invites both results to stand together, and gives the bound that
must ride with the second: "one event in 53 differential resets, zero in 49
with the patches, timing-dependent, and my protocol cannot tell a genuinely
hung block from a lost completion. It bounds; it does not prove."

The 25 August result belongs on the patches that close the race, 2/14 and
3/14, NOT on 4/14: his message was a reply to `[PATCH v9 02/13]` and he calls
it "the silent flavour of the race THESE TWO PATCHES close". 4/14's 45-reset
paragraph is about the domain dropping, and of it he says "That is what the
patch text describes, and it is right."

⚠ The differential removed both patches together, so the evidence bounds the
PAIR and not either one of them.

## What stands

Everything. The v10 cover's paragraph, both of Igor's Tested-by lines with
their conditions as he sent them, and 4/14's paragraph about the 19 August
differential ("45 induced resets across three cores ... so this is not
rocket-wide"). No patch in v12 needs to change.
