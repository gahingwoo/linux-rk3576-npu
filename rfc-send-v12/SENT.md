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

## v12 -- NOT SENT, on purpose

v12 is prepared (README.md here). It waits for a reply on v11.

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

## 2026-09-05 Tested-by on Igor's patch -- PREPARED, NOT SENT
`reply-igor-testedby.eml` + `send-reply-testedby.sh` (DRY=1 clean).
In-Reply-To `<20260904125936.26234-1-royalnet026@gmail.com>`, which is Igor's
core-removal PATCH rather than the DVFS thread.

Why it exists: the same `Tested-by` already went out on 2026-09-05 05:13, but
in the DVFS thread. Igor asked at 07:01 for it on the patch itself -- a tag in
another thread is not under the patch, so b4 will not collect it when Tomeu
applies, and him reposting it on our behalf reads as a from/email mismatch.
Same tag, same test, correct thread. He will carry it on his next revision if
we do not send this.

Also from that mail, for the record: the climbing accel minor is a devm leak,
not just "the next free minor". `rocket_device_init()` uses
`devm_drm_dev_alloc()` against the module's `rknn` platform device, which is
only unregistered in `rocket_unregister()`; `rocket_device_fini()` calls
`drm_dev_unregister()` and nothing else, so the minor's `xa_erase()` drmm
action waits for the last `drm_dev_put()` at module exit. Every unbind leaves
an unregistered drm_device holding its minor. Igor's, on his own patch.
