#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send [PATCH v15 00/15] accel/rocket: RK3576 NPU (RKNN) enablement.
#
# WHAT v15 IS. v14 rebased onto next-20261030, because v14's 12/15 stopped
# applying to linux-next: Sidong Yang's regcmd validation put two defines
# where 12/15 adds its own. Fourteen patches are byte for byte v14's (same
# patch-id, same message and tags); 12/15 differs in context only. The
# GPU QoS restore fix that sat in the prepared v15 as 09/16 went out on its
# own on 2026-11-01 (rfc-send-qos/) and is NOT in this series.
#
# Recipients are v14's plus Leonard Lausen, whom the cover cites.
#
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/v15-send.log

REGEN=${REGEN:-1}
TREE=${TREE:-$HOME/Desktop/linux-next-v8}
#
# BOTH OF THESE WERE HARDCODED AND BOTH WENT STALE. BRANCH was `v12-prep`
# and BASE was `master`, which in that clone is pinned at next-20260814 -- so
# REGEN=1 kept re-emitting a base-commit that was 29 days old and unreachable
# from any branch, and it would have silently ignored a rewritten series on a
# new branch. The clone is SHALLOW, so refreshing the base needs a real
# `git fetch --depth 1 origin tag next-YYYYMMDD` first; bumping BASE alone
# gets you "fatal: bad revision".
#
# v15 is the branch to send: next-20261030 plus the fifteen patches.
# NOT v15-prep, which also carries the QoS fix that was sent separately;
# defaulting to it would post that patch a second time.
BRANCH=${BRANCH:-v15}
#
# The base is next-20261030. This clone is SHALLOW; to move it:
#
#     git -C "$TREE" fetch --depth 1 origin tag next-YYYYMMDD
#     git -C "$TREE" rebase --onto next-YYYYMMDD next-20261030 v15
#
# and then set BASE and re-run the baseline before sending.
#
BASE=${BASE:-next-20261030}
if [ "$REGEN" = 1 ]; then
	rm -f v15-0*.patch
	# --base, OR THE NOTE ASSERTS SOMETHING THE MAIL DOES NOT CARRY.
	#
	# v8 carried BOTH machine readable lines:
	#   base-commit: 4477a78374a57c3809b172ad30cceabda48c47c6
	#   prerequisite-patch-id: 46ebb679e93d3d25393e8cbf8fc3c955bcc01bd4
	# v9 already regressed to a single base-commit naming Igor's commit as
	# the base, and this script -- written to fix the note that format-patch
	# had eaten -- dropped both: no --base, and no format.useAutoBase in
	# $TREE. --base=master puts v8's pair back, which is the form that says
	# "the base is next-20260814 AND you also need this patch", rather than
	# folding the prerequisite into the base and losing it.
	#
	# That is the SAME failure it exists to fix. 5/13's note says in as many
	# words "which this series' base-commit is", so posting without the
	# trailer points a reviewer at something the mail does not contain -- and
	# the reviewer it points at is Rob Herring's bot, whose "a different
	# dependency should be noted in this patch" is the whole reason the note
	# exists. Igor caught the missing Notes block in v9 by reading exactly
	# this carefully.
	git -C "$TREE" format-patch --notes -v15 --cover-letter \
	    --base="$BASE" \
	    -o "$PWD" "$BASE..$BRANCH" >/dev/null
	for f in 0*.patch; do [ -e "$f" ] && mv "$f" "v15-$f"; done
	# THE COVER LETTER COMES BACK AS *** BLURB HERE ***. It is written in
	# cover-blurb.txt so that regenerating cannot throw it away.
	./splice-cover.py v15-0000-cover-letter.patch cover-blurb.txt
	# NOT `! grep -q …`. A command whose status is inverted by `!` is
	# exempt from errexit, so that line checked nothing at all: it printed
	# nothing and did not abort. send-email refuses a cover whose SUBJECT is
	# still the placeholder, but it never looks at the body.
	# ANY *** MARKER, not only format-patch's two. v13's blurb carries
	# "*** BASE HERE ***" where the base tag goes, because the base has to
	# be refreshed before this goes out and the sentence around it claims
	# the series applies to that tag. A cover with a marker in it is a
	# draft. (v12's marker was "*** BOARD RESULT HERE ***", for the answer
	# to Sashiko's 4/14 finding.)
	if grep -q '\*\*\*' v15-0000-cover-letter.patch; then
		echo "the cover still has a *** marker in it:" >&2
		grep -n '\*\*\*' v15-0000-cover-letter.patch >&2; exit 1
	fi

	# AND CHECK THE TRAILER CAME OUT. --base is silent when the revision
	# it names is not an ancestor: format-patch would simply not emit it, and
	# this script would go on to send a series whose note cites a base-commit
	# nobody can see.
	b=$(grep -lc '^base-commit:' v15-*.patch 2>/dev/null | wc -l)
	[ "$b" -ge 1 ] || { echo "no base-commit trailer was emitted -- 5/13 cites one" >&2; exit 1; }
	echo "base-commit trailer on:"
	grep -l '^base-commit:' v15-*.patch | sed 's/^/  /'
	echo "regenerated $(ls v15-0*.patch | wc -l) patches"
	echo "01/15 is: $(sed -n 's/^Subject: //p' v15-0001-*.patch | head -1)"
	echo "         $(sed -n 's/^From: //p' v15-0001-*.patch | head -1)"
fi

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')

CC=(--cc='royalnet026@gmail.com'          # Igor Paunovic, Tested-by 2,3,4/15, Reviewed-by 5/15
    #
    # EVERYONE WHOSE TAG THE SERIES CARRIES GETS THE MAIL. Three were
    # missing and none of them is on the To list under another address:
    # Abel Vesa reviewed 9/14 and 10/14, and Sebastian Reichel and Sidong
    # Yang gave 1/14 its Reviewed-by and Tested-by. A reviewer who does not
    # receive the version carrying his tag cannot object when it stops
    # applying, which is exactly what happened to 10/14 in this version.
    # Krzysztof and Conor are covered by krzk+dt@ and conor+dt@ on To.
    #
    --cc='abel.vesa@oss.qualcomm.com'     # Abel Vesa, Reviewed-by 9/15 and 10/15
    --cc='sebastian.reichel@collabora.com' # Sebastian Reichel, Reviewed-by 1/15
    --cc='sidong.yang@furiosa.ai'         # Sidong Yang, Tested-by 1/15
    --cc='u.kleine-koenig@baylibre.com'   # Uwe Kleine-Koenig, the header on 11/13
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, confirmed the PC_TASK_CON layout
    --cc='diederik@cknow-tech.com'        # Diederik de Haas, the iommu binding
    # flipper.net, AND MAINTAINERS IS THE STALE ONE. Line 3879 still says
    # "Alexey Charkov <alchark@gmail.com>", and an audit of this script read
    # that line and called this address wrong -- "silently failing since v5".
    # It is not. He reviewed THIS SERIES at v2 from alchark@flipper.net on
    # 2026-07-21, and he was still posting from it on 2026-08-27; the gmail
    # address has not been seen since July. Changing it on the strength of
    # MAINTAINERS would have moved five revisions of correct Cc onto an
    # address he has stopped using.
    --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2
    --cc='leonard@lausen.nl'              # Leonard Lausen, runs v14 on a NanoPi M5 (the cover cites him)
    # get_maintainer.pl lists these two as blamed_fixes: they committed the
    # rocket commits the series' Fixes: tags name. v14 left them out.
    --cc='jeff.hugo@oss.qualcomm.com'     # Jeff Hugo, accel, blamed_fixes
    --cc='rfoss@kernel.org'               # Robert Foss, blamed_fixes
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

# READ IT OFF THE COVER, DO NOT SPELL IT. This line was hardcoded from v10
# and said 00/13 over a series of fourteen, because a version bump renamed the
# v10 in it and left the count alone. A summary that can disagree with the mail
# it is summarising is worse than no summary.
# INVISIBLE UNICODE AND NON-ASCII. A mail with a zero-width character or a
# bidi mark in it may not go through, and a cover drafted by a tool may carry
# one without anyone seeing it. Names in trailers are the one legitimate
# non-ASCII; nothing in this series has any.
CLEAN=$HOME/.claude/skills/unicode-format-cleaner/scripts/clean_unicode.py
for f in v15-*.patch; do
	if [ -f "$CLEAN" ] && ! python3 "$CLEAN" --detect "$f" >/dev/null 2>&1; then
		echo "$f carries invisible Unicode; refusing" >&2; exit 1
	fi
	if grep -qP '[^\x00-\x7F]' "$f"; then
		echo "$f has non-ASCII bytes:" >&2; grep -nP '[^\x00-\x7F]' "$f" | head -3 >&2; exit 1
	fi
done

echo "Send $(sed -n 's/^Subject: //p' v15-0000-cover-letter.patch | head -1)"
echo "     From: $(sed -n 's/^From: //p' v15-0000-cover-letter.patch | head -1)"
printf '  To : %s\n' "${TO[@]#--to=}"
printf '  Cc : %s\n' "${CC[@]#--cc=}"
echo
ls v15-00*.patch | sed 's/^/  /'
echo
# THE NOTES GUARD LIVES HERE NOW, NOT INSIDE the REGEN block. The promise
# made on-list was "refuses to send unless the number of patches carrying a
# Notes block is exactly one", and it was only true on the default path:
# REGEN=0 skipped the regeneration AND the check, and sent whatever was on
# disk. A guarantee with an env var that turns it off is not a guarantee.
#
# AND ZERO HAS TO SAY SO. `grep -lc … | wc -l` returning 0 makes the
# pipeline fail under pipefail, so the script died at the assignment before
# it could print why. It refused, silently, which is the shape of failure
# this whole version exists to remove.
# THE NOTE GUARD INVERTS AT v11, AND THAT IS A DECISION, NOT AN ACCIDENT.
#
# v10 required exactly one Notes block: Rob Herring's bot had asked for the
# dependency to be recorded in the patch rather than only in the cover, and the
# dependency was Igor's clock patch sitting OUTSIDE the series. v11 carries
# that patch as 01/15, so there is no dependency outside the series left to
# record, and the note's own text named a prerequisite-patch-id trailer this
# version deliberately does not emit.
#
# The note did not survive the cherry-pick onto the new base, because git notes
# follow the sha. That is the right outcome and it happened by accident, which
# is exactly the kind of thing to make deliberate: a Notes block that comes
# back is stale by construction, and this refuses to send it.
n=$(grep -lc '^Notes:' v15-*.patch 2>/dev/null | wc -l || true)
[ "$n" = 0 ] || { echo "a Notes block is back on $n patch(es); 01/15 is inside the series, so it has nothing left to say" >&2; exit 1; }
b=$(grep -lc '^base-commit:' v15-*.patch 2>/dev/null | wc -l || true)
[ "$b" -ge 1 ] || { echo "no base-commit trailer was emitted" >&2; exit 1; }
# AND prerequisite-patch-id MUST BE GONE. It is the line Sashiko cannot
# follow -- "Sashiko is not reviewing this series because it doesn't not
# understand yet prerequisite-patch-id" -- and bundling Igor's patch is what
# removes it. If it is back, the bundling did not take and this is the series
# Tomeu has already asked us to change.
q=$(grep -lc '^prerequisite-patch-id:' v15-*.patch 2>/dev/null | wc -l || true)
[ "$q" = 0 ] || { echo "prerequisite-patch-id is still on $q patch(es) -- the prerequisite did not get bundled" >&2; exit 1; }
# AND IGOR'S PATCH HAS TO BE 01/15 WITH HIS NAME ON IT. The whole point of
# this version is that his patch travels inside the series; posting it under
# the wrong author, or not posting it at all, is the one way to get this wrong
# that nobody would notice until he did.
# FIFTEEN, AND NOT THE QoS FIX. That patch was sent on its own on
# 2026-11-01; the branch it also sits on (v15-prep) is one letter away from
# this one, and posting it twice is the mistake this line refuses.
np=$(ls v15-00[0-9][0-9]-*.patch | grep -vc -- '-0000-' || true)
[ "$np" = 15 ] || { echo "expected 15 patches, found $np" >&2; exit 1; }
! grep -l 'do not restore QoS that was never saved' v15-*.patch >/dev/null 2>&1 || {
	echo "the QoS fix is in this series; it was sent separately" >&2; exit 1; }
grep -q '^From: Igor Paunovic' v15-0001-*.patch || {
	echo "01/15 is not authored by Igor Paunovic" >&2; exit 1; }
for t in 'Sidong Yang' 'Diederik de Haas' 'Sebastian Reichel'; do
	grep -q "$t" v15-0001-*.patch || {
		echo "01/15 has lost $t's tag" >&2; exit 1; }
done

# A DRY RUN, because there was no way to see the final headers without
# committing to the send. --confirm=never means the Cc list git harvests from
# the trailers -- Conor at microchip, Krzysztof at oss.qualcomm, Abel Vesa --
# is never shown to anyone before it goes.
if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	git send-email --dry-run --confirm=never "${TO[@]}" "${CC[@]}" v15-*.patch
	exit 0
fi

echo "This sends 16 messages for real (cover + 15). DRY=1 shows the headers instead."
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" v15-*.patch 2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
[[ -n "$CID" ]] && echo && echo "lore: https://lore.kernel.org/all/$CID/"
