# v14, what has gone out

## v14 -- SENT 2026-09-24, 16 messages, all 250

Message-ID `20260924102135.92217-1-gahing@gahingwoo.com`,
<https://lore.kernel.org/all/20260924102135.92217-1-gahing@gahingwoo.com/>
`base-commit: 1a1de54f7369cd2b5bac0f265910e60ad3a6b4c3` (next-20260914, unchanged
from v13), branch `v14-prep` in `~/Desktop/linux-next-v8`. These .patch files
are a record now and must not be edited.

**What changed from v13, and who asked:**

- 10/15 (code): one reset rather than an array (Philipp Zabel); the reset
  pointer is cleared under pmu->mutex before it is put (Sashiko). Abel Vesa's
  Reviewed-by kept, and the cover asks him whether it should go.
- 3/15 (comment only): the other half of the -EINVAL ambiguity (Sashiko).
  Message quotes Igor Paunovic's 19 September statement verbatim; his earlier
  summary is behind the Links, and the cover asks whether he wants it back.
- 13/14 split into 13/15 and 14/15 (Heiko Stuebner); the two add exactly what
  13/14 added.
- 7/15 carries Heiko's Reviewed-by.
- Every message except 1/15 (Igor's) cut hard, at the user's request after
  Ulf and Heiko asked for it on theirs. The cover went from 279 lines (v13) to
  about 50.

**Two numbers corrected that v12 and v13 had put on the list:**
- 12/15 no longer claims its test was byte exact; it was within one count,
  as the README has said since 17 August.
- 14/15 gives 786 MHz at 750 mV as 11 to 25 wrong words a pass. v12 and v13
  said 13 to 20 wrong rows, a figure that entered on 12 September with no
  source.

**Pre-send review** by a separate reviewer found two more that would have gone
out: the cover pointed at "the 9/15 thread" (not yet existing; the settle
result is under v13's 9/14), and 12/15's PC_TASK_CON comment said the count
clear lands on a bit that does nothing, when on RK3576 BIT(13) sits inside the
task number and inflates it. Both fixed; a second pass found no blocking
problems. The trim before that had also dropped 3/15's five Link: lines,
caught by diffing every tag line against v13 rather than parsing trailers.

**Verified before sending:** 15 commits each build both touched subsystems,
W=1 clean, dt_binding_check on three bindings, 74 rk3576/rk3588 dtbs with the
one pre-existing rk3588-rock-5b-pcie-ep complaint, checkpatch raising only
9/15's existing macro-style warnings. On the board (r421), a CI build of the
series with the release config: both cores probe, full regression green,
perplexity identical to the last digit. Settle-delay question answered on v13
as posted (r420).

**Open, as the cover lists:** 4/15 the fix for the asynchronous put, if wanted;
5/15 against ZhaoJinming's patch on the same line; 14/15 one or two NPU domains
per core; the rocket_core_fini() ordering bug; holding 15/15 a cycle.
