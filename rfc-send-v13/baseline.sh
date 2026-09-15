#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
#
# The mechanical baseline the cover letter claims, as a script.
#
# WHY THIS FILE EXISTS. v13's cover says "bisectable: the two touched
# subsystems build at each of the 14 commits, and W=1 on the final tree is
# warning free. dt_binding_check passes; dtbs_check is clean on five rk3576
# boards and three rk3588 ones." All of that was run by hand, against
# next-20260911. When the base is refreshed it has to be re-run, and a
# baseline that lives in somebody's shell history cannot be re-run identically
# -- which is the same fault as a check that only exists as a sentence.
#
# It prints one line per step and STOPS at the first failure, because a
# cover letter that claims a clean baseline must not be sent over a run whose
# failures scrolled past.
#
#   rfc-send-v13/baseline.sh <TREE> <BASE_TAG> <BRANCH>
#
# e.g. baseline.sh ~/Desktop/linux-next-v8 next-20260914 v13-prep-914
set -e
TREE=${1:?usage: baseline.sh TREE BASE_TAG BRANCH}
BASE=${2:?base tag}
BR=${3:?branch}
J=${J:-$(nproc)}
SUBSYS="drivers/accel/rocket/ drivers/pmdomain/rockchip/"

cd "$TREE"
[ -z "$(git status --porcelain)" ] || { echo "!! tree is dirty; refusing"; exit 1; }
git rev-parse -q --verify "$BASE" >/dev/null || { echo "!! no such tag: $BASE"; exit 1; }

echo "== 0. what is being checked"
echo "   tree   $TREE"
echo "   base   $BASE  $(git rev-parse --short "$BASE^{commit}")"
echo "   branch $BR    $(git rev-parse --short "$BR")"
echo "   commits on top of the base: $(git rev-list --count "$BASE..$BR")"
echo

echo "== 1. bisectable: both touched subsystems build at every commit"
# --exec runs after EACH commit is applied, which is what bisectable means.
# A plain build of the tip says nothing about the intermediate states.
git rebase --exec "make -j$J -s $SUBSYS >/dev/null" "$BASE" "$BR"
echo "   ok   $(git rev-list --count "$BASE..$BR") commits, each builds"
echo

# A PIPE MASKS THE EXIT STATUS. `make ... | tee log | tail` has tail's status,
# so `set -e` cannot see make fail, and a make that dies without printing the
# word "error:" would slip past the grep below as well. Redirect, check, then
# show. Same fault this project just closed in tests/board_regress.sh.
run_checked() {
	if ! sh -c "$1" > "$2" 2>&1; then
		echo "   !! the command itself failed: $1"
		tail -20 "$2"
		exit 1
	fi
}

echo "== 2. W=1 on the final tree, warning free"
run_checked "make -j$J W=1 $SUBSYS" /tmp/baseline-w1.log
tail -3 /tmp/baseline-w1.log
if grep -qE "warning:|error:" /tmp/baseline-w1.log; then
	echo "   !! W=1 is not clean:"
	grep -E "warning:|error:" /tmp/baseline-w1.log | head -20
	exit 1
fi
echo "   ok   no warnings"
echo

echo "== 3. dt_binding_check on the three bindings this series touches"
# THE NAMES COME FROM THE PATCHES, NOT FROM MEMORY. The NPU binding is
# rockchip,rk3588-rknn-core.yaml -- the RK3576 is added to the RK3588 file,
# it does not get one of its own -- and a DT_SCHEMA_FILES that matches
# nothing makes yamllint exit with a usage error rather than checking zero
# files quietly, which is the only reason the first run of this was caught.
SCHEMAS="npu/rockchip,rk3588-rknn-core.yaml"
SCHEMAS="$SCHEMAS power/rockchip,power-controller.yaml"
SCHEMAS="$SCHEMAS iommu/rockchip,iommu.yaml"
for y in $SCHEMAS; do
	[ -r "Documentation/devicetree/bindings/$y" ] || {
		echo "   !! no such binding: $y"; exit 1; }
done
# ONE make PER SCHEMA. A space-separated DT_SCHEMA_FILES does not survive to
# the tools here: yamllint comes back "one of the arguments FILE_OR_DIR is
# required" and dt-check-style "no input files", which is zero files checked
# reported as a failure. One at a time is unambiguous and it also says WHICH
# binding failed.
#
# And the grep excludes make's own jobserver notice. "Unable to reopen
# jobserver read-side pipe" is a -j artefact of the recursive make, not a
# schema complaint, and counting it makes every clean run read as dirty.
for y in $SCHEMAS; do
	run_checked "make -j$J dt_binding_check DT_SCHEMA_FILES='$y'" \
		/tmp/baseline-binding.log
	if grep -vE "jobserver" /tmp/baseline-binding.log |
	   grep -qE "warning|error|Error"; then
		echo "   !! $y is not clean"
		grep -vE "jobserver" /tmp/baseline-binding.log |
			grep -E "warning|error|Error" | head -10
		exit 1
	fi
	echo "   ok   $y"
done
echo

echo "== 4. dtbs_check over every rk3576 and rk3588 target"
#
# TWO WAYS THIS REPORTS CLEAN WITHOUT CHECKING ANYTHING, and the first run of
# this script hit both.
#
#   - the target is relative to arch/arm64/boot/dts, so `rockchip/` from the
#     top is right and `arch/arm64/boot/dts/rockchip/...` gets the prefix
#     doubled;
#   - CHECK_DTBS only runs when a dtb is actually REBUILT. With the dtbs
#     already built, make says "Nothing to be done" and the complaint list is
#     empty because nothing was examined.
#
# So the dtbs are removed first, and the count of "DTC [C]" lines is checked
# against the number of targets the Makefile lists. An empty complaint list
# over zero files is the shape of every silent pass this project has shipped.
#
MK=arch/arm64/boot/dts/rockchip/Makefile
# THE TARGETS COME FROM THE MAKEFILE AND ARE NAMED ONE BY ONE. `rockchip/`
# from the top says "Nothing to be done" -- it is not a target make knows --
# and `make CHECK_DTBS=1 dtbs` works but builds every arm64 platform, which is
# 1500 files to check 85. Each target named individually is both precise and
# what the cover claims.
# sort -u, BECAUSE THE MAKEFILE NAMES SOME TARGETS TWICE. Overlay-composed
# boards appear both in their own rule and in the overlay list, and make
# refuses with "target given more than once in the same rule".
# ANCHORED ON THE LINE END, or .dtbo overlays come through as .dtb targets:
# the trailing .* swallowed the "o" and make then says "No rule to make
# target" for a file that is an overlay and not a device tree.
TARGETS=$(sed -nE 's/^dtb-\$\(CONFIG_ARCH_ROCKCHIP\) \+= (rk35(7|8)[0-9a-z._-]*\.dtb)[[:space:]]*$/rockchip\/\1/p' "$MK" | sort -u)
# FROM SCRATCH, which is what the cover claims and what a half-finished
# earlier build makes impossible: a killed make leaves a truncated .cmd or .d
# behind and fixdep then fails on a file it cannot open, which looks like a
# schema failure and is not one.
rm -f arch/arm64/boot/dts/rockchip/rk357*.dtb arch/arm64/boot/dts/rockchip/rk358*.dtb
rm -f arch/arm64/boot/dts/rockchip/.rk357*.cmd arch/arm64/boot/dts/rockchip/.rk358*.cmd
rm -f arch/arm64/boot/dts/rockchip/.rk357*.d arch/arm64/boot/dts/rockchip/.rk358*.d
# -j1 HERE AND NOWHERE ELSE. An overlay-composed target and the base dtb it
# is composed from can be built in parallel, and then fixdep opens a .d the
# base has not finished writing: "No such file or directory" on a file the
# build itself is creating. Serial, this is four minutes for 77 targets.
run_checked "make -j1 CHECK_DTBS=1 $(echo $TARGETS | tr '\n' ' ')" \
	/tmp/baseline-dtbs.log
N76=$(echo "$TARGETS" | grep -c 'rk357' || true)
N88=$(echo "$TARGETS" | grep -c 'rk358' || true)
NT=$((N76 + N88))
echo "   the Makefile lists $N76 rk3576 targets and $N88 rk3588 ones, $NT distinct"
CHECKED=$(grep -cE "DTC \[C\]|OVL \[C\]" /tmp/baseline-dtbs.log || true)
echo "   dtbs actually checked: $CHECKED"
if [ "$CHECKED" -lt "$NT" ]; then
	echo "   !! fewer files checked than targets listed; a clean run over"
	echo "      nothing is not a clean run"
	exit 1
fi
# A dtbs_check COMPLAINT SAYS NEITHER "warning" NOR "error". Its format is
#   <path>.dtb: <node> (<compatible>): <what is wrong>
# and the wording is "Unevaluated properties are not allowed", "is not of
# type", "does not match". Grepping for warning|error over this log reports a
# clean run with the complaints sitting in it, which is what the first version
# of this line did. Match the FORMAT instead.
echo "   complaints on rk3576 and rk3588:"
grep -E "^[^ ].*\.dtb: .*:" /tmp/baseline-dtbs.log | sort -u | head -20 || true
NCOMP=$(grep -cE "^[^ ].*\.dtb: .*:" /tmp/baseline-dtbs.log || true)
echo "   $NCOMP complaint line(s)"
echo
echo "== done. base $BASE, branch $BR, $CHECKED dtbs checked"
