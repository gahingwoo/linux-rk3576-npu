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
- the RESERVED_0 34-against-66 table is offered on request. It is not written
  up anywhere yet; if he asks, it comes from decoding 0x4050 out of
  vendor-capture/geom/*.rknn.
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

## v10 itself

NOT sent. send-v10.sh regenerates with --notes and refuses unless exactly one
patch carries a Notes block. The cover letter's prose is unwritten;
CHANGELOG-DRAFT.md holds the factual delta only.
