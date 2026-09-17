# Extra patches

Applied by the kernel CI after the `rfc-send-v13/` series, in filename order.

`rfc-send-v13/` is the NPU series as it goes upstream and nothing unrelated
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
