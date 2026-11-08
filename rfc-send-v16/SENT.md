# v16, what has gone out

## v16 -- SENT 2026-11-08, 17 messages, then two replies, all 250

Message-ID `20261108065917.135194-1-gahing@gahingwoo.com`,
<https://lore.kernel.org/all/20261108065917.135194-1-gahing@gahingwoo.com/>
`base-commit: ddfe51b0a0f5` (next-20261105), branch `v16-wip` in
`~/Desktop/linux-next-v8`. These .patch and .eml files are a record now and
must not be edited.

**Why v16:** Tomeu asked (v15 3/15, 2026-11-04) for all LLM-written text in the
accel/rocket patches to be replaced by Jiaxing's own, and for a GET_PARAM
ioctl. Heiko reviewed v15 (Reviewed-by on 1, 2, 4, 5, 9, 10) and asked why each
core lists both power domains and why the IOMMU takes five clocks. Chaoyi asked
for a comment in 11/15 to go. Sashiko's v15 4/15 point stood.

**What changed from v15:**
- Commit messages, cover and comments: written by Jiaxing in Chinese,
  translated with an LLM. Comments added by the series removed (3, 5, 11, 12).
  1/16 (Igor's) shortened and marked "[Jiaxing: shortened the commit message]".
- 4/16 drops the runtime PM reference after rocket_core_reset().
- New 13/16: DRM_IOCTL_ROCKET_GET_PARAM, HW_VERSION, RK3588 = 1, RK3576 = 2.
- One power domain per core (6/16 binding, 12/16 driver code removed, 15/16).
- NPU IOMMU takes four clocks, not five: the npu clock dropped (8/16, 15/16).
- Heiko's v15 tags picked up; Igor's Tested-by on 4/16 dropped; the five Links
  on 3/16 dropped.

**Measured for it (ROCK 4D, 2026-11-08):** IOMMU with aclk+iface, +npu, or one
CBUF clock fails its reset; with both CBUF clocks it works without npu. Each
core on only its own domain: correct on both cores. 4/16 A/B under a 2 ms job
timeout: v15 order hung the board twice (board-logs/v16-ab-v15order-hang.klog),
v16 order never hung in four runs, but the IOMMU did not recover either way
(known issue in the cover). Final v16 on the ROCK 4D and the CM5-IO (Armbian
edge 7.3.3, fork branch rk3576-npu-v16-final): charsiu board_regress all pass,
ppl 41.1009 on both, 0 timeouts, 0 IOMMU errors.

**Checked before sending** (rfc-send-v14/baseline.sh on next-20261105, with
dtschema 2026.9): every commit builds both subsystems, W=1 clean,
dt_binding_check on the three bindings, dtbs_check over 80 rk3576/rk3588 DTBs
with the two pre-existing complaints (rk3582-radxa-e54c, rk3588-rock-5b-pcie-ep).

**Replies sent after the series:** reply-tomeu.eml and reply-heiko.eml, both
under the v15 3/15 messages they answer.

**Recipients:** v15's, plus Shawn Lin and Finley Xiao (reviewed the QoS fix).
