# Non-NPU-block (GRF/CRU/power) writes — vendor vs rocket, the dimension the NPU writel audit missed (2026-07-05)

The NPU-register-block writel audit + bare task_number=N are exhausted (chained CMAC empty with the vendor's
exact NPU software). Firmware is ruled out (board boots the vendor SPI TF-A+OP-TEE). This reviews the ONE
untested layer: what the vendor rknpu driver writes OUTSIDE the NPU block (0x2770_xxxx) — GRF/CRU/power —
that rocket + the DTS don't. Read-only; register-space semantics flagged as hypotheses.

## PART 1 — the vendor's only non-NPU-block writes
Enumerated all of rk3576-vendor-kernel/drivers/rknpu/. The ONLY direct non-NPU register writes are:
- **npu_grf READ-MARGIN** (rknpu_devfreq.c:78 `rk3576_npu_set_read_margin`):
  `regmap_write(grf, 0x08, 0x001c0000 | (rm<<2)); 0x0c, 0x003c0000|(rm<<2); 0x10, 0x001c0000|(rm<<2)`.
  - grf = `&npu_grf` = **syscon@26018000** (rk3576.dtsi:1965, "rockchip,rk3576-npu-grf").
  - `rm` (read-margin) from the OPP table `volt-mem-read-margin` (rk3576.dtsi:2483):
    `855000->1  765000->2  675000->3  495000->4` (higher voltage = lower rm number).
  - The 0x001c0000/0x003c0000 upper halves are GRF hiword write-masks (bits 2-4); rm sits at bits 2-4.
  - WHEN: via the OPP framework (`npu_opp_config_regulators` / set_read_margin hook) at OPP init AND on
    every voltage change. So it's set at probe (init-freq 950 MHz) and per devfreq transition.
- Everything else is the standard frameworks, not direct MMIO: clk (assigned-clock CLK_RKNN_DSU0=198 MHz,
  OPP `rockchip,opp-clocks` = ACLK_RKNN_CBUF / HCLK_RKNN_CBUF / PCLK_NPUTOP_ROOT), reset (SRST_A_RKNN0/1),
  power-domains (PD_NPU0/1/NPUTOP), nvmem (npu_leakage / npu_opp_info / serial → OPP bin/process select),
  operating-points-v2 (npu_opp_table, init-freq 950 MHz, low-temp-min-volt 750 mV).
- No CRU/PMU-GRF/other direct writes. bw_priority disabled on RK3576. sram/nbuf are IOMMU-mapped, not written.

## PART 2 — what rocket + the DTS set in those spaces
- rocket writes the SAME npu_grf **0x26018000** — but ONLY the URGENT QoS regs `0x6c/0x70/0x74/0x78 =
  0x01ff01ff` (rocket_drv.c:349, npu_urgent). It **never writes the read-margin 0x08/0x0c/0x10.**
- rocket does NOT use the Rockchip OPP/read-margin mechanism (no rockchip_opp_info, no volt_rm_tbl). It sets
  voltage + clocks directly via module params: npu_uv (regulator_set_voltage), aclk_hz, cbuf_clk_hz,
  npu_clk_hz (PVTPLL), with the voltage-before-PVTPLL ordering. Clocks it manages: aclk, hclk, npu, pclk,
  **aclk_cbuf, hclk_cbuf** (clks[4]/[5]).
- So vs the vendor: rocket sets its OWN operating point (params), and leaves the npu_grf read-margin at its
  power-on DEFAULT (whatever bits 2-4 of 0x08/0x0c/0x10 are at reset), never matched to its voltage.

## PART 3 — diff + ranked candidates
There IS a concrete non-NPU-block write the vendor makes that rocket does not: **the npu_grf read-margin.**
Ranked by (likelihood it affects the CBUF→CSC→CMAC consume × cheapness):

1. **npu_grf read-margin (0x26018000 + 0x08/0x0c/0x10)** — (a) vendor sets rm (voltage-tied) at OPP init +
   per voltage change; (b) rocket never writes it (only URGENT at 0x6c-0x78 in the same GRF); (c)
   **thematically on-target: the read-margin governs on-chip SRAM read timing, and CBUF is that SRAM — the
   exact stage of the wall (operands reach CBUF but the CMAC's CSC read comes back empty).** A read-margin
   mismatched to rocket's operating voltage could make the CSC's tight CBUF operand read fail (return zeros)
   -> empty accumulator -> zero-point, which is precisely the symptom. (d) CHEAP: rocket already ioremaps
   0x26018000 for URGENT — add `writel(0x001c0000|(rm<<2), grf+0x08); 0x003c0000|(rm<<2) @0x0c;
   0x001c0000|(rm<<2) @0x10`, rm chosen from the table for rocket's NPU voltage (e.g. ~800 mV -> rm=1 or 2).
   **CAVEAT (weakens, doesn't kill):** conv0 also reads CBUF and computes fine, so the default margin isn't
   catastrophically wrong; a marginal read-margin would tend to cause errors rather than uniform-empty. But
   the chained CSC operand-read path may be more timing-critical than conv0's staging, and this is the only
   concrete GRF diff + it's right on the CBUF SRAM theme -> test it first. RANK #1.
2. **CBUF clock rate (ACLK_RKNN_CBUF / HCLK_RKNN_CBUF)** — the vendor OPP-manages these (rockchip,opp-clocks);
   rocket sets aclk_cbuf via cbuf_clk_hz. Same CBUF-SRAM-timing theme as #1: if rocket's CBUF clock differs
   from the vendor's OPP rate, the CBUF read/write timing (and the read-margin relationship) is off. Pairs
   with #1. Cheap to check/match. RANK #2.
3. **NPU operating point (voltage/freq, init-freq 950 MHz, nvmem bin/process)** — rocket sets its own
   voltage+freq via params, not the vendor OPP table; conv0 works so the basic point is viable, but the
   read-margin/CBUF-timing in #1/#2 is only correct AT the vendor's operating point. Confirm rocket's actual
   NPU voltage + CBUF clock vs the vendor OPP so #1's rm value matches. RANK #3 (context for #1/#2).

**VERDICT:** the platform-software dimension is NOT matched — the vendor sets the npu_grf read-margin (and
OPP-manages the CBUF clocks) and rocket does neither. This is a concrete, DTS/probe-settable candidate that
is thematically aligned with the exact wall (CBUF SRAM read into the CMAC). Test #1 first (write the
read-margin matched to rocket's voltage; oracle = chained output distinct 0-point -> real). If it does NOT
arm the CSC, then GRF/CBUF-timing is matched too and the platform-software dimension is also exhausted ->
RTL. Register-space/offset semantics (rm field = bits 2-4; read-margin governs CBUF timing) are hypotheses
from the vendor code + the RK OPP read-margin convention, not TRM-verified.
