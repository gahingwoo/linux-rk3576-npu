# Extra patches

Applied by the kernel CI after the NPU series, in filename order. The series
is the `rfc-send-<SERIES>/` directory named by `SERIES` in
`.github/workflows/kernel.yml`, v14 today.

That directory is the series as it goes upstream, and nothing unrelated
belongs in it. Anything else this board needs goes here instead.

| Patch | What it does | Verified on hardware |
|---|---|---|
| `0001-drm-bridge-synopsys-dw-hdmi-qp-...-340MHz.patch` | HDMI TMDS rates above 340 MHz: SCDC scrambling and the 1/40 bit clock ratio. Without it 2560x1440@100 is pruned on CM5-IO. | yes, 2026-09-17 |

## 0001, verified

CM5-IO, kernel `...-00015-g5b273d685f96`, AOC 2560x1440 panel. Read back from
the sink's own SCDC registers via
`/sys/kernel/debug/dri/1/HDMI-A-1/scdc_status`, with the mode held by
`sleep 45 | modetest -M rockchip -s 73@71:2560x1440-100`:

    active mode:  2560x1440 100.00  397980
    Scrambling Enabled     : yes
    TMDS Bit Clock Ratio   : 1/40
    Channel 0/1/2 Locked   : yes
    Channel 0/1/2 Errors   : 0


## 0001 is a stopgap: upstream is already doing this, better

**Do not send 0001 upstream.** Checked 2026-09-18: Cristian Ciocaltea — the
author named in `dw-hdmi-qp.c`'s own header — has a series in flight called
**"Add HDMI 2.0 support to DW HDMI QP TX"**, at **v11 of 12, posted
2026-09-01**, still under review. It covers the same ground and much more:

- SCDC scrambling and the high TMDS clock ratio above 340 MHz,
- `drm_scdc_start_scrambling()`, `drm_scdc_stop_scrambling()` and
  `drm_scdc_sync_status()`, which run a periodic work item watching the
  sink's scrambling status, where 0001 writes SCDC once and sleeps 100 ms,
- an HDMI version enum and connector/bridge scrambling infrastructure,
- and it was tested on **Radxa ROCK 4D, which is RK3576** — the same SoC.

Sending 0001 would duplicate the driver author's own work.

**Timing, which matters for anyone planning around a distro kernel:** this
tree is based on 7.3-rc3, so the 7.3 merge window was long closed when v11
was posted. A 74-patch feature series lands in **7.4 at the earliest**. A
stock Fedora 45 kernel (7.3) will therefore *not* have HDMI 2.0 scrambling,
and 2560x1440@100 will be pruned again on a fresh install. Keep 0001 until
the series lands, then drop it.

**The useful contribution is a Tested-by, not a patch.** The series was
tested on ROCK 4D and not on CM5-IO, and the verification above reads the
sink's own SCDC registers rather than just noting that the mode appeared.
