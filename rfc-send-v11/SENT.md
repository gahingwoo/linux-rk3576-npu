# Sent

Both sent 2026-08-31.

## reply-igor-bundling.eml -- SENT

Tells Igor his patch is being carried inside v11 before he sees it as 01/14.
Tomeu asked for the bundling on the v10 cover because Sashiko will not review
a series whose dependency is a prerequisite-patch-id it cannot follow.

    In-Reply-To: <20260729130743.128876-1-royalnet026@gmail.com>
    To:          royalnet026@gmail.com
    Cc:          linux-rockchip, dri-devel, tomeu@tomeuvizoso.net

Sent 2026-08-31 20:03 +1200, SMTP result 250.

    Message-ID: <20260831080356.80952-1-gahing@gahingwoo.com>

What it commits us to, and it is short on purpose:

- his patch goes out UNCHANGED, under his name, his Signed-off-by first and
  mine underneath as the carrier;
- it goes out "with the four tags it has collected". That sentence is a
  promise, and send-v11.sh is what keeps it: it refuses to send a 01/14 not
  authored by Igor Paunovic or missing any of Sidong Yang's, Diederik de
  Haas's or Sebastian Reichel's tag.

⚠ Two paragraphs were cut from the draft before it went, both correctly.
One offered to drop the patch from the series if he preferred a v3 -- an
offer nobody asked for, and one that would have had to be honoured. The
other confessed that our tree's copy carried only our own Reviewed-by and
would have posted his patch three reviews short. That is our bookkeeping and
not his problem; the check for it belongs in the send script, where it is.

## v11 itself -- SENT

Sent 2026-08-31 20:19 +1200. Fifteen messages, all SMTP result 250, no
failures, visible on lore.

    Cover:  <20260831081956.84871-1-gahing@gahingwoo.com>
    01..14: <20260831081956.84871-2..15-gahing@gahingwoo.com>

⚠ git send-email auto-Cc'd Diederik de Haas off 01/14's Tested-by line,
which is the cheapest possible confirmation that Igor's three recovered
tags really travelled.

The cover went out at 54 lines, down from 122. What came out of it: the
provenance history of Igor's patch, the link to its standalone posting,
Igor's RK3588 differential for the third time, and the tag bookkeeping.
What stayed: the note's removal (Rob Herring's bot asked for that note in
v8 and removing it silently invites the complaint again), the binding
check results, and the two open questions -- 9/14 possibly wanting a
split, and 13/14's power domain topology, which has still had no reply.

14 patches plus a cover. Igor's is 01/14, ours are 02/14 through 14/14, and
every diff is byte identical to v10 -- `git diff v10-prep v11-prep` is empty.

    range:  master..v11-prep     (NOT d589af989.., which is what v10 used)
    base-commit: 4477a78374a57c3809b172ad30cceabda48c47c6
    prerequisite-patch-id: NONE, deliberately

⚠ THE GUARD INVERTED. v10 refused to send unless exactly ONE patch carried a
Notes block; v11 refuses if ANY does. The note existed because the dependency
was outside the series and Rob Herring's bot asked for it to be recorded in
the patch; it is inside now, and the note's own text named a trailer this
version does not emit. It did not survive the cherry-pick because git notes
follow the sha -- the right outcome, reached by accident, now enforced.

⚠ The script also refuses if 01/14 is not authored by Igor Paunovic or has
lost any of the three tags his tree-copy was missing. That is the one way to
get this version wrong that nobody would notice until he did.

Verified before sending: 14 of 14 apply in order to a plain next-20260814;
the tree is identical to v10-prep; nine review tags across the series, four
of them on 01/14.
