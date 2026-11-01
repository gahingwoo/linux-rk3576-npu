# v15, what has gone out

## v15 -- SENT 2026-11-01, 16 messages, all 250

Message-ID `20261101082307.151957-1-gahing@gahingwoo.com`,
<https://lore.kernel.org/all/20261101082307.151957-1-gahing@gahingwoo.com/>
`base-commit: 7649ba73f9e7` (next-20261030), branch `v15` in
`~/Desktop/linux-next-v8`. These .patch files are a record now and must not be
edited.

**What changed from v14:** a rebase. v14's 12/15 stopped applying to
linux-next when Sidong Yang's regcmd validation (applied by Heiko on
2026-10-12) put ROCKET_MAX_REGCMDS and ROCKET_REGCMD_ALIGN where 12/15 adds its
PC_TASK_CON defines; they now follow his. `git range-diff` against v14: the
other fourteen are `=`, and every message and tag is identical.

The GPU QoS restore fix that sat in the prepared v15 as 09/16 was sent on its
own the same morning (rfc-send-qos/) and is not in this series.

**Why it was sent although nobody asked:** v14 no longer applied to
linux-next, so any maintainer picking it up would first have had to ask for a
rebase; the weekly patch-drift check had been red since 2026-10-26 (and had
been testing v13 by mistake, fixed in 7aae0d3). The rebase stood in for a
ping after five weeks without a human reply on v14.

**The cover** is short on purpose (Tomeu, 2026-09-24, on long LLM-written
text): why the rebase, Leonard Lausen's NanoPi M5 run, Sashiko's two v14 9/15
points as measured on a CM5-IO (board-logs/r422, r423), 1/15 being Igor's,
routing, and 15/15's dependency on 9, 10 and 12 to 14.

**Recipients:** v14's, plus Leonard Lausen (cited in the cover) and Jeff Hugo
and Robert Foss, whom get_maintainer.pl lists as blamed_fixes and v14 had
left out.

**Checked before sending** (rfc-send-v14/baseline.sh on branch v15): every
commit builds both subsystems, W=1 clean, dt_binding_check on the three
bindings, dtbs_check over all 78 rk3576/rk3588 DTBs with two complaints, both
pre-existing in linux-next and in files the series does not touch
(rk3588-rock-5b-pcie-ep, rk3582-radxa-e54c's rtl8365mb switch). A test copy
of the cover went to the sender first.

**Armbian is not affected:** its edge kernel is 7.3.y, which does not have
Sidong's defines, so armbian/build#11162 and #11163 rightly carry v14's form
of 12/15. When Armbian's edge moves to 7.4 it needs v15's.
