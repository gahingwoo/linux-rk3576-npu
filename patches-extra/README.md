# Extra patches

Applied by the kernel CI after the `rfc-send-v13/` series, in filename order.

`rfc-send-v13/` is the NPU series as it goes upstream and nothing unrelated
belongs in it. Anything else this board needs goes here instead.

| Patch | What it does | Verified on hardware |
|---|---|---|
| `0001-drm-bridge-synopsys-dw-hdmi-qp-...-340MHz.patch` | HDMI TMDS rates above 340 MHz: SCDC scrambling and the 1/40 bit clock ratio. Without it 2560x1440@100 is pruned on CM5-IO. | not yet |
