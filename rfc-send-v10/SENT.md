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
- "I have corrected the comment to say so" refers to the Mesa tree commit
  cc907006, which has NOT been pushed to merge request 43804. Pushing it is
  still an open decision.

## v10 itself

NOT sent. send-v10.sh regenerates with --notes and refuses unless exactly one
patch carries a Notes block. The cover letter's prose is unwritten;
CHANGELOG-DRAFT.md holds the factual delta only.
