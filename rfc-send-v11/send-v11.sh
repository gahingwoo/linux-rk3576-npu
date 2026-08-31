#!/usr/bin/env bash
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
#
# Send [PATCH v11 00/14] accel/rocket: RK3576 NPU (RKNN) enablement.
#
# To and Cc are scripts/get_maintainer.pl over all thirteen patches, which
# returns exactly the v8 set, plus the reviewers who are not in it and whose
# v8 comments this version answers.
#
# ⚠ NEW SINCE v8: Uwe Kleine-Koenig, who asked for the narrower device-id
# header on v8 10/12 and is not in the maintainer list for anything the series
# touches. 11/13 answers him and he should see it.
#
# ⚠⚠ --notes IS NOT OPTIONAL. v9's cover letter said 05/13 carried a git note
# naming the base and the one prerequisite, and the posted mail had no Notes
# section: this script's v9 ancestor never passed --notes, so the note in the
# repository was simply not emitted. Igor caught it on the thread on 25 August
# and Rob's bot had asked for the dependency on v8. Regenerate here rather than
# trusting whatever is in the directory.
set -euo pipefail
cd "$(dirname "$0")"
LOG=/tmp/v11-send.log

REGEN=${REGEN:-1}
TREE=${TREE:-$HOME/Desktop/linux-next-v8}
if [ "$REGEN" = 1 ]; then
	rm -f v11-0*.patch
	# ⚠⚠ --base, OR THE NOTE ASSERTS SOMETHING THE MAIL DOES NOT CARRY.
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
	git -C "$TREE" format-patch --notes -v11 --cover-letter \
	    --base=master \
	    -o "$PWD" master..v11-prep >/dev/null
	for f in 0*.patch; do [ -e "$f" ] && mv "$f" "v11-$f"; done
	# ⚠ THE COVER LETTER COMES BACK AS *** BLURB HERE ***. It is written in
	# cover-blurb.txt so that regenerating cannot throw it away.
	./splice-cover.py v11-0000-cover-letter.patch cover-blurb.txt
	# ⚠ NOT `! grep -q …`. A command whose status is inverted by `!` is
	# exempt from errexit, so that line checked nothing at all: it printed
	# nothing and did not abort. send-email refuses a cover whose SUBJECT is
	# still the placeholder, but it never looks at the body.
	if grep -q "SUBJECT HERE\|BLURB HERE" v11-0000-cover-letter.patch; then
		echo "the cover still has a placeholder in it" >&2; exit 1
	fi

	# ⚠ AND CHECK THE TRAILER CAME OUT. --base is silent when the revision
	# it names is not an ancestor: format-patch would simply not emit it, and
	# this script would go on to send a series whose note cites a base-commit
	# nobody can see.
	b=$(grep -lc '^base-commit:' v11-*.patch 2>/dev/null | wc -l)
	[ "$b" -ge 1 ] || { echo "no base-commit trailer was emitted -- 5/13 cites one" >&2; exit 1; }
	echo "base-commit trailer on:"
	grep -l '^base-commit:' v11-*.patch | sed 's/^/  /'
	echo "regenerated $(ls v11-0*.patch | wc -l) patches"
	echo "01/14 is: $(sed -n 's/^Subject: //p' v11-0001-*.patch | head -1)"
	echo "         $(sed -n 's/^From: //p' v11-0001-*.patch | head -1)"
fi

TO=(--to='tomeu@tomeuvizoso.net' --to='heiko@sntech.de' --to='robh@kernel.org'
    --to='krzk+dt@kernel.org' --to='conor+dt@kernel.org' --to='joro@8bytes.org'
    --to='will@kernel.org' --to='robin.murphy@arm.com' --to='ulfh@kernel.org'
    --to='p.zabel@pengutronix.de' --to='ogabbay@kernel.org'
    --to='zhangqing@rock-chips.com')

CC=(--cc='royalnet026@gmail.com'          # Igor Paunovic, Tested-by 1/13, Reviewed-by 4/13
    --cc='u.kleine-koenig@baylibre.com'   # Uwe Kleine-Koenig, the header on 11/13
    --cc='chaoyi.chen@rock-chips.com'     # Chaoyi Chen, confirmed the PC_TASK_CON layout
    --cc='diederik@cknow-tech.com'        # Diederik de Haas, the iommu binding
    # ⚠⚠ flipper.net, AND MAINTAINERS IS THE STALE ONE. Line 3879 still says
    # "Alexey Charkov <alchark@gmail.com>", and an audit of this script read
    # that line and called this address wrong -- "silently failing since v5".
    # It is not. He reviewed THIS SERIES at v2 from alchark@flipper.net on
    # 2026-07-21, and he was still posting from it on 2026-08-27; the gmail
    # address has not been seen since July. Changing it on the strength of
    # MAINTAINERS would have moved five revisions of correct Cc onto an
    # address he has stopped using.
    --cc='alchark@flipper.net'            # Alexey Charkov, reviewed v2
    --cc='dri-devel@lists.freedesktop.org' --cc='linux-rockchip@lists.infradead.org'
    --cc='iommu@lists.linux.dev' --cc='linux-pm@vger.kernel.org'
    --cc='devicetree@vger.kernel.org' --cc='linux-arm-kernel@lists.infradead.org'
    --cc='linux-kernel@vger.kernel.org')

# ⚠ READ IT OFF THE COVER, DO NOT SPELL IT. This line was hardcoded from v10
# and said 00/13 over a series of fourteen, because a version bump renamed the
# v10 in it and left the count alone. A summary that can disagree with the mail
# it is summarising is worse than no summary.
echo "Send $(sed -n 's/^Subject: //p' v11-0000-cover-letter.patch | head -1)"
echo "     From: $(sed -n 's/^From: //p' v11-0000-cover-letter.patch | head -1)"
printf '  To : %s\n' "${TO[@]#--to=}"
printf '  Cc : %s\n' "${CC[@]#--cc=}"
echo
ls v11-00*.patch | sed 's/^/  /'
echo
# ⚠⚠ THE NOTES GUARD LIVES HERE NOW, NOT INSIDE the REGEN block. The promise
# made on-list was "refuses to send unless the number of patches carrying a
# Notes block is exactly one", and it was only true on the default path:
# REGEN=0 skipped the regeneration AND the check, and sent whatever was on
# disk. A guarantee with an env var that turns it off is not a guarantee.
#
# ⚠ AND ZERO HAS TO SAY SO. `grep -lc … | wc -l` returning 0 makes the
# pipeline fail under pipefail, so the script died at the assignment before
# it could print why. It refused, silently, which is the shape of failure
# this whole version exists to remove.
# ⚠⚠ THE NOTE GUARD INVERTS AT v11, AND THAT IS A DECISION, NOT AN ACCIDENT.
#
# v10 required exactly one Notes block: Rob Herring's bot had asked for the
# dependency to be recorded in the patch rather than only in the cover, and the
# dependency was Igor's clock patch sitting OUTSIDE the series. v11 carries
# that patch as 01/14, so there is no dependency outside the series left to
# record, and the note's own text named a prerequisite-patch-id trailer this
# version deliberately does not emit.
#
# The note did not survive the cherry-pick onto the new base, because git notes
# follow the sha. That is the right outcome and it happened by accident, which
# is exactly the kind of thing to make deliberate: a Notes block that comes
# back is stale by construction, and this refuses to send it.
n=$(grep -lc '^Notes:' v11-*.patch 2>/dev/null | wc -l || true)
[ "$n" = 0 ] || { echo "a Notes block is back on $n patch(es); v11's dependency is 01/14, so it has nothing left to say" >&2; exit 1; }
b=$(grep -lc '^base-commit:' v11-*.patch 2>/dev/null | wc -l || true)
[ "$b" -ge 1 ] || { echo "no base-commit trailer was emitted" >&2; exit 1; }
# ⚠ AND prerequisite-patch-id MUST BE GONE. It is the line Sashiko cannot
# follow -- "Sashiko is not reviewing this series because it doesn't not
# understand yet prerequisite-patch-id" -- and bundling Igor's patch is what
# removes it. If it is back, the bundling did not take and this is the series
# Tomeu has already asked us to change.
q=$(grep -lc '^prerequisite-patch-id:' v11-*.patch 2>/dev/null | wc -l || true)
[ "$q" = 0 ] || { echo "prerequisite-patch-id is still on $q patch(es) -- the prerequisite did not get bundled" >&2; exit 1; }
# ⚠ AND IGOR'S PATCH HAS TO BE 01/14 WITH HIS NAME ON IT. The whole point of
# this version is that his patch travels inside the series; posting it under
# the wrong author, or not posting it at all, is the one way to get this wrong
# that nobody would notice until he did.
grep -q '^From: Igor Paunovic' v11-0001-*.patch || {
	echo "01/14 is not authored by Igor Paunovic" >&2; exit 1; }
for t in 'Sidong Yang' 'Diederik de Haas' 'Sebastian Reichel'; do
	grep -q "$t" v11-0001-*.patch || {
		echo "01/14 has lost $t's tag" >&2; exit 1; }
done

# ⚠ A DRY RUN, because there was no way to see the final headers without
# committing to the send. --confirm=never means the Cc list git harvests from
# the trailers -- Conor at microchip, Krzysztof at oss.qualcomm, Abel Vesa --
# is never shown to anyone before it goes.
if [ "${DRY:-0}" = 1 ]; then
	echo "DRY=1: headers only, nothing is sent."
	git send-email --dry-run --confirm=never "${TO[@]}" "${CC[@]}" v11-*.patch
	exit 0
fi

echo "This sends 14 messages for real. DRY=1 shows the headers instead."
read -rp "Send now? [y/N] " a; [[ "${a:-}" == [yY] ]] || { echo "aborted."; exit 1; }

git send-email --confirm=never "${TO[@]}" "${CC[@]}" v11-*.patch 2>&1 | tee "$LOG"

CID=$(grep -m1 -oiE "Message-Id: <[^>]+>" "$LOG" | sed 's/.*<//;s/>.*//')
[[ -n "$CID" ]] && echo && echo "lore: https://lore.kernel.org/all/$CID/"
