# Sent

## reply-igor-sizee-oc64.eml

Sent 2026-08-27 13:49 +1200, SMTP result 250.

    Message-ID:   <20260827014924.254513-1-gahing@gahingwoo.com>
    In-Reply-To:  <CAEWPSH7AcRb4uAnhmcL+kk3mQrgqYsQAYR=JQjJdkFGVK4qfHw@mail.gmail.com>
    To:           royalnet026@gmail.com
    Cc:           linux-rockchip@lists.infradead.org, dri-devel@lists.freedesktop.org

    lore: https://lore.kernel.org/all/20260827014924.254513-1-gahing@gahingwoo.com/

What it commits us to, so the next version can be checked against it:

- v10 goes out, and it is v9 plus six tags and the note with no code change.
- the two Tested-by comments stay distinct: 02/13 carries "differential base",
  03/13 does not.
- the RESERVED_0 table: HE ASKED on 2026-08-27 17:48 and it is now written,
  in reply-igor-reserved0.eml, regenerable by reserved0-build.py. NOT SENT.

  ⚠ IT RETRACTS THE CLAIM WE MADE. "Follows the model series rather than the
  geometry" does not survive: all 94 files carry one toolkit build string,
  g_pw24 carries both values in a single compile, and fixing the WHOLE CNA
  geometry leaves twelve classes that carry both (g_cal against bias_k5 is
  the named pair). There is also a third value, 38, on the 58 depthwise
  dispatches, which "34 against 66" never mentioned. What RESERVED_0 does
  track is DPU 0x4044, 364 of 364 on the regular datapath.
- "I have corrected the comment to say so" is TRUE against what Igor can see.
  Checked 2026-08-31 by cloning the MR branch itself: gitlab.freedesktop.org
  gahingwoo/mesa rk3576-main is at 484a840079f8, and its rkt_regcmd.c reads

    "SIZE_E_1 is 0 in all 81 regular ones and 1 in all 13 depthwise ones.
     Its axis is the depthwise flag rather than the channel count, so no
     output channel count selects it, and upstream's 1 is simply the
     depthwise value."

  ⚠ An earlier draft of this file said the opposite -- that the correction
  had NOT been pushed and that pushing it was an open decision -- and an
  audit repeated it back. Both were wrong. cc907006 on the working branch is
  a separate, additional rewrite that is not in the MR; the sentence said
  on-list was never about that commit.

  ⚠ Still not public, and it should be: cc907006 also credits Igor by name
  for the depthwise padding. If that attribution was meant for him it is not
  in the MR yet.

## reply-igor-reserved0.eml

Sent 2026-08-31 16:07 +1200, SMTP result 250.

    Message-ID:   <20260831040751.24030-1-gahing@gahingwoo.com>
    In-Reply-To:  <CAEWPSH5_PmfUCEm5O53=32NQjPKMd4vm--Y2R=4ErMoehtt=tA@mail.gmail.com>
    To:           royalnet026@gmail.com
    Cc:           linux-rockchip@lists.infradead.org, dri-devel@lists.freedesktop.org

What it commits us to:

- it RETRACTS "RESERVED_0 follows the model series rather than the geometry"
  on-list. If that phrasing is used again anywhere, it contradicts a public
  correction.
- it states RESERVED_0 <-> DPU 0x4044 as 364 of 364 on the REGULAR datapath
  only, and says the depthwise value 38 breaks the pairing. Do not widen it.
- it offers reserved0-build.py "if you want to re-run it against your own
  corpus". If he asks, it is rfc-send-v10/reserved0-build.py.
- it says what selects the 0x4044 arm is still open. It is.

## v10 itself

SENT 2026-08-31 16:08 +1200. Fourteen messages, all SMTP result 250, no
failures. Visible on lore.

    Cover:  <20260831040804.24111-1-gahing@gahingwoo.com>
    01..13: <20260831040804.24111-2..14-gahing@gahingwoo.com>
    lore:   https://lore.kernel.org/all/20260831040804.24111-1-gahing@gahingwoo.com/

⚠ A count of "10 of 14" appeared while it was in flight. That was a grep
filter on a backgrounded pipeline truncating its own capture, not a
half-posted series: /tmp/v10-send.log has 14 Message-IDs and 14 results of
250. Read the tee'd log, never the filtered view, before believing a send
went wrong.
