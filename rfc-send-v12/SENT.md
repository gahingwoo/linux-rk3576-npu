# Sent

## reply-igor-script.eml -- SENT

The script behind the RESERVED_0 table, which Igor asked for on 2026-09-02
10:02 in the v9 05/13 thread. Sent 2026-09-03 23:22 +1200, SMTP result 250.

    Message-ID:   <20260903112208.952061-1-gahing@gahingwoo.com>
    In-Reply-To:  <20260902100147.16191-1-royalnet026@gmail.com>
    To:           royalnet026@gmail.com
    Cc:           linux-rockchip@lists.infradead.org, dri-devel@lists.freedesktop.org

What it commits us to:

- the script in it "needs numpy and nothing else": true, the container
  reader is inlined and the rest is the standard library;
- "the parts of the page that only hold for my files print only when those
  files are present": true, gated on MINE, exercised on a six-file subset
  that has none of them;
- "the What it does follow block tests the 0x4044 pairing ... and reports
  one-to-one or not, with the counts": true, it computes both directions
  and prints the verdict it computed.

What it does NOT commit us to: nothing about v12, nothing about a date.

The cover was passed through the no-dashes, no-filler edit before it went;
the script's own prose keeps its double hyphens, it is a file.

## v12 -- SENT 2026-09-12 18:50 NZST, 15 of 15 at 250

    Message-ID:  <20260912065053.1519165-1-gahing@gahingwoo.com>
    base-commit: 68142f986ff04b2b70b31db00f719bf690f64a9a (next-20260911)
    lore: https://lore.kernel.org/all/20260912065053.1519165-1-gahing@gahingwoo.com/

Cover plus fourteen, every one 250, all fourteen In-Reply-To the cover.
12 To, 15 Cc.

The reason it stopped waiting: v11 got zero human replies in twelve days, and
the Sashiko review Tomeu named as the unblocker arrived 76 minutes after v11
was posted and has been sitting unacted on. v7.3-rc2 is out, so the v7.4
window is five to six weeks away.

What it commits us to, and all of it is now public:

- 3/14 tests "> 0", and the cover states why "!= 0" was withdrawn:
  pm_runtime_get_conditional() tests power.disable_depth before
  power.runtime_status, so -EINVAL masks a suspended device. If that reading
  is wrong, the patch is wrong.
- 10/14 cycles the resets BEFORE the settle delay. This is a change to code
  Abel Vesa reviewed and the cover says so and offers to drop his tag.
- 13/14's numbers: 192 MHz is worth 4.0 to 4.2% of decode with both cores,
  a core is worth 26 to 37% on a 1B model. Boot-to-boot drift under 1%,
  measured by booting 594 twice. Artifact: board-logs/r388.
- the genpd figures on 4/14: 46.8 s active, 14.2 s idle, usage +202 over one
  60.8 s decode. Artifact: board-logs/r387.
- the withdrawal of the 11 September mail about Igor's two runs.
- that 5/14 collides textually with ZhaoJinming's stable-marked fix.

What it does NOT claim: that the posted series has booted. The board ran the
three code fixes on a different lineage, which carries Igor's attach-domain
refactor and max_cores; neither is posted here.

## 2026-09-04 reply to Igor's DVFS RFC
`reply-igor-dvfs.eml`, sent 2026-09-04 23:08 NZST, msgid
`<20260904110853.85150-1-gahing@gahingwoo.com>`, Result 250.
In-Reply-To `<20260903091646.7183-1-royalnet026@gmail.com>` (his 09-03 09:17,
the mail that named the voltage-vs-frequency gap).
To Igor; Cc Tomeu Vizoso, Huseyin BIYIK, linux-rockchip, dri-devel.
Says: the two-core fault is solved and the fix is a voltage; the four device
tree rows; both fixes and what each costs; v12 takes 594 MHz in the SoC dtsi;
the run he should do on RK3588 (all three cores loaded at 900 and 1000 MHz on
850 mV) before settling an OPP table; the SCMI ordering that hangs this board.

## 2026-09-04 question to Nicolas Dufresne, same thread
`reply-nicolas-dts.eml`, sent 23:19 NZST, msgid
`<20260904111902.87135-1-gahing@gahingwoo.com>`, Result 250.
In-Reply-To `<c495dae1976dab842d77f4a4a142217eb77b6fb7.camel@ndufresne.ca>`
(his 2026-08-17, the RK3588 DVFS proof of concept). To Nicolas; Cc Igor,
Tomeu, linux-rockchip, dri-devel. He removed the assigned clock and rate from
his DTS and wants the driver to run with no OPP table; this says the rate is
load bearing on RK3576 until something carries the rail, with the four rows,
and asks whether it holds on RK3588.

## 2026-09-05 reply to Igor: the S-o-b answer and his fix tested on RK3576
`reply-igor-sob.eml`, sent 2026-09-05 17:13 NZST, msgid
`<20260905051323.189794-1-gahing@gahingwoo.com>`, Result 250.
In-Reply-To `<20260904124659.25971-1-royalnet026@gmail.com>`.
To Igor; Cc Tomeu, linux-rockchip, dri-devel.
Says: drop our Signed-off-by on his 1/7 copy, keep Reviewed-by on both;
`Tested-by: Jiaxing Hu # RK3576, two cores` with the two unbind/rebind rounds
(`bound: 0` then `bound: 2`, cores 0 and 1 both times) and nine models
identical; that the first unbind Oopses on our kernel for a reason that is
ours (attach-once detaching in rocket_job_fini through a group
rocket_core_fini had already put), with the trace; and that an accel device
takes the next free minor, which cost an hour.

## 2026-09-05 Tested-by on Igor's patch -- SENT
Sent 21:01 NZST, Result 250, msgid
`<20260905090134.239404-1-gahing@gahingwoo.com>`.
`reply-igor-testedby.eml` + `send-reply-testedby.sh` (DRY=1 clean).
In-Reply-To `<20260904125936.26234-1-royalnet026@gmail.com>`, which is Igor's
core-removal PATCH rather than the DVFS thread.

Why it exists: the same `Tested-by` already went out on 2026-09-05 05:13, but
in the DVFS thread. Igor asked at 07:01 for it on the patch itself -- a tag in
another thread is not under the patch, so b4 will not collect it when Tomeu
applies, and him reposting it on our behalf reads as a from/email mismatch.
Same tag, same test, correct thread.

Also from that mail, for the record: the climbing accel minor is a devm leak,
not just "the next free minor". `rocket_device_init()` uses
`devm_drm_dev_alloc()` against the module's `rknn` platform device, which is
only unregistered in `rocket_unregister()`; `rocket_device_fini()` calls
`drm_dev_unregister()` and nothing else, so the minor's `xa_erase()` drmm
action waits for the last `drm_dev_put()` at module exit. Every unbind leaves
an unregistered drm_device holding its minor. Igor's, on his own patch.

## 2026-09-12 the correction to what v10 said about Igor's differential

`reply-igor-correction.eml`, sent 2026-09-12 00:28 NZST, msgid
`<20260911122832.1364839-1-gahing@gahingwoo.com>`, Result 250.
In-Reply-To `<20260831040804.24111-1-gahing@gahingwoo.com>`, the v10 cover.
To Igor; Cc Tomeu, linux-rockchip, dri-devel.

⚠ It replies to the COVER, not to him. The false sentence is in the archive
under that message; a correction that only reached his mailbox would leave
the cover saying he reproduced something he reported he could not.

What it retracts: "a job signalled completion with its output buffer never
written, all 48 channels 0x80" and "across 102 induced resets in nine runs it
appeared only on the arm without them". Also names the 27 August mail to him,
`<20260827014924.254513-1-gahing@gahingwoo.com>`, as the other instance.

⛔⛔ **THIS MAIL WAS WRONG AND HAS BEEN WITHDRAWN.** Igor reported the 102
resets and the all-0x80 buffer himself, on 2026-08-25, in
`CAEWPSH5mxTbUkNouxm6yecMZYvDowquhvYvhaXQ8HoMtHD5U1g@mail.gmail.com`, six days
before the v10 cover quoted him. The 45-reset run (19 August) and the
102-reset run (25 August) are different sessions and do not conflict. I read
only the 19 August thread and treated its silence as an absence.

⚠ **The withdrawal rides in the v12 cover rather than as a third mail on the
thread.** Two standalone mails on one misquote is more noise than the misquote;
the paragraph is in `cover-blurb.txt` before "The tags:", so it goes out when
v12 does and nothing is sent in the meantime. Corrected record in
`rfc-send-v10/RETRACTION.md`.

⚠ Nothing it "commits us to" holds. In particular there is no restriction on
which of Igor's results may be cited: both runs are his and both are quotable.
