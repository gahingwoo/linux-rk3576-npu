# Sent

Nothing in this directory has been sent.

## reply-igor-bundling.eml -- NOT SENT, and it goes FIRST

Tells Igor his patch is being carried inside v11 before he sees it as 01/14.
Tomeu asked for the bundling on the v10 cover because Sashiko will not review
a series whose dependency is a prerequisite-patch-id it cannot follow.

    In-Reply-To: <20260729130743.128876-1-royalnet026@gmail.com>
    To:          royalnet026@gmail.com
    Cc:          linux-rockchip, dri-devel, tomeu@tomeuvizoso.net

What it commits us to:

- his patch goes out unchanged, his authorship and Signed-off-by first;
- all four of his tags travel with it, listed with the dates of the mails
  that gave them so he can check them;
- if he would rather send a v3 standalone, we drop it from the series. That
  offer is on the record and has to be honoured if he takes it.

## v11 itself -- NOT SENT

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
