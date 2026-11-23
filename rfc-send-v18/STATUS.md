v18 status: DRAFT, not sent, not run on a board
================================================

Prepared 2026-11-23. Nothing in this directory has been sent.

Bases
-----

- pd/  (3 patches): Ulf's pmdomain next, 6f5c8ec9302c (2026-11-14, the
  newest on 2026-11-23). Branch v18-pd.
- npu/ (8 patches): next-20261120 (the newest linux-next tag on
  2026-11-23). Branch v18-npu.

v17 rocket 1-4 are in v7.4-rc4, through drm-misc-fixes-2026-11-20:
b2895c801511 (clocks by name), 6995680ff5bb (job_lock), dce0eba182f2
(synchronize_irq), 36161ff0c00f (suspend after reset). v18 carries only
v17 5-12.

Other rocket changes upstream since v17 that v18 sits on:
5c4aeafcac8c (Chaoyi Chen, core->iommu_group instead of
iommu_group_get()), 97e48904cbdb (Igor, core index from DT position),
c3fe8795ecd8 (drm_mm UAF fix, rocket_vm), Triet Hoang's sched/alloc
fixes, Haoming Gao's submit fixes.

Changes from v17
----------------

pd:
- 1/3: Tested-by Vladimir Bely (R76S) and Sidong Yang (RK3588, ROCK 5B+).
- 3/3: dropped "In his review of v16" from the message.
- Otherwise unchanged; applies as is on the newer pmdomain next.

npu (v17 number -> v18 number):
- 05 -> 1: rebased; the new rocket_job_next_locked() uses
  core->iommu_group (5c4aeafcac8c). Carries Sidong's Tested-by.
- 06 -> 2, 07 -> 3: unchanged (Krzysztof R-b, Conor Ack).
- 08 -> 4: REWRITTEN as Daniel Drake asked. No soc data, no counts:
  devm_clk_bulk_get_all() and devm_reset_control_array_get_exclusive().
  The enum rocket_clk (named for Heiko in v17) is gone, since nothing
  indexes the clocks. Suggested-by Daniel. Sidong's v17 tag dropped.
- 10 -> 5: GET_PARAM now comes BEFORE the RK3576 patch, with RK3588 only.
  The hardware version is match data, stored in rocket_device before the
  DRM device is registered (no READ_ONCE, no cores[0]); a core with a
  different version is refused. uAPI doc no longer says "one value per
  compatible". Kept our own enum instead of PC_VERSION: the RK3568
  reads 0 from it (lore b05f7154-e85f-4207-80ae-f080282ba780@rock-chips.com,
  "Rockchip NPU core 0 version: 0"). Sidong's v17 tag dropped.
- 09 -> 6: REWRITTEN. "# Conflicts:" lines gone. TASK_CON_RK3576 is a
  generated register in rocket_registers.h (Mesa gen_header.py output,
  diff for Mesa's registers.xml in mesa-registers-xml-TASK_CON_RK3576.diff),
  selected by hw_version. Cores counted in rocket_drv.c and passed to
  rocket_device_init(). Sidong's v17 tag dropped.
- 11 -> 7: message rewritten: no lab notes, 594 MHz explained as the
  rate valid at the boot voltage (vendor OPP: 500 and 600 MHz both need
  725 mV; board boots 786 MHz at 750 mV).
- 12 -> 8: message says npu-supply is required by the binding, set on
  RK3588 boards too, and used by no driver; the rail is switched by the
  power domain through domain-supply.

Checks done (desk only)
-----------------------

- Every npu prefix builds rocket.ko with W=1: 0 warnings.
- pm-domains.o builds with W=1 on v18-pd: 0 warnings.
- checkpatch --strict: only line length in the generated register block
  and in the uAPI ioctl define (same as the existing lines), and the
  DOMAIN_ macro table warnings that the existing table already has.
- dt_binding_check (rknn-core, rockchip iommu): clean.
- dtbs_check rk3576-rock-4d.dtb: clean.
- No line starting with "#" in any commit message.

NOT done
--------

- Board: the ROCK 4D was away. 4/8 (get_all, reset array), 5/8 and 6/8
  are new code and have not run. Needed before sending: probe on the 4D,
  r10-style 30 runs, GET_PARAM returns 2.
- RK3588: 4/8 changes RK3588 probe too; ask Sidong to rerun.
- Cover letters and changelogs: to be written (user writes, I translate).
- Replies on the v17 thread: Daniel (04/08/09/10/11/12), sashiko (03,
  04, 11: the PD resets it asks for were dropped on purpose in v17).
- Mesa: the registers.xml change has to go to the Mesa MR too.
- Send script: add a check that fails on any "#" line in a message.

Armbian
-------

armbian/build#11496 (rpardini, open): v7.4-rc4, carries v17 5-12 rebased
by hand. Same resolution as ours for 5/12. He asks for a v18 so it can be
a plain b4 dump. Checked 2026-11-23: all 8 v18 npu patches apply with
git am -3 on v7.4-rc4 (applied only, not built there).

Review by a separate agent (2026-11-23, code reading only)
----------------------------------------------------------

Checked by me against the source before acting; messages only, no code
changed (the CI run below builds the same code):

- npu 8/8 needs pd 2/3, or nothing holds vdd_npu_s0 and the regulator
  core turns it off as unused. 8/8 now says so; the cover must too.
- npu 4/8: reset_control_bulk_deassert() walks backwards and
  reset_control_array_deassert() forwards, so the RK3588 deassert order
  is now srst_a then srst_h (was srst_h then srst_a). Said in the
  message; Sidong's RK3588 rerun should force timeouts, since only the
  reset path calls rocket_core_reset().
- pd 1/3: a failing child returns at once, so its unvisited siblings are
  not tried either, and genpd still lists them off. Message now says
  that; same point CodeRabbit made on #11366.
- pd 3/3: "top-level domain" was wrong (PD_NPU is above NPUTOP).
  Reworded.

Not taken: a dev_err on a core with a different hw_version (Daniel
asked for no print on programming errors).

CI: gahingwoo/build branch rk3576-npu-v18-test, run 45096808024
(v7.4-rc4 + PR 11496 + v18 pd and npu, radxa-rock-4d bleedingedge).

CI result: run 45096808024 passed. The log shows all 11 v18 patches
applied (272-274 pmdomain, 275-282 rocket, after the Lausen GPU patch),
rocket and pm-domains compiled with no warnings, and the rock-4d,
cm5-io and r76s dtbs built. Kernel debs are in the run's artifacts, for
the board test.

Board (r429, 2026-11-23): probe, GET_PARAM = 2, 30/30 runs identical
(5e3aaf1a5a57) with no error. Forced timeouts: 5 of 6 recover; one
back-to-back timeout left both IOMMUs failing and the output silently
wrong, also after the domain had gone off, until a driver reload. The
cover's known-issue paragraph must say this. NPU-disabled boot (N.dtb)
not run yet.
