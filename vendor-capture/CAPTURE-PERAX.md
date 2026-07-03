# Per-axis coefficient-buffer capture (next board session)

**Goal:** capture the vendor's live SDP coefficient buffer for a genuinely **per-axis**
conv, the one thing only the board can give. For per-axis the float surface decodes to the
dequantised weights (derivable) — so a clean capture lets the `rkt_coefs.c` encoder be written
to *reproduce known bytes* instead of guessing, and avoids another "I was certain, board said no".

## What's in the image
`buildroot/br-out/images/sdcard-cap.img` (vendor kernel + rootfs-cap). On boot, `S98npucap` runs
`/opt/npu-cap/run-capture.sh`, which captures TWO convs through the vendor rknn stack under
`capture.so`:

- **perax** = `c2d_perax.rknn` — conv2d's exact weights/shape (OC128/IC16/K5), but quantised
  **per-channel** by the toolkit (`conv_perax.py`, `quantized_method="channel"`). Float surface
  should decode to the dequant weights.
- **pertensor** = `conv2d_rk3576.rknn` — the per-tensor blob, for contrast.

The SDP coefficient buffer is the tail of `bo01`: weights are `bo01[0:51200]`, coef = `bo01[51200:]`.

## How to run
Flash `sdcard-cap.img`, boot, capture the serial console to a log. The capture is automatic.
Board fragility note: this is the **vendor** kernel (robust), not mainline rocket — no
`drm_mm_takedown` wedge, both convs should run.

## How to retrieve (two ways)
1. **Easiest — the boot log.** The console prints, for each tag:
   ```
   -----BEGIN perax COEF B64-----
   <base64 of the ~20800B coef tail>
   -----END perax COEF B64-----
   ```
   Just send the boot log; I decode both blocks. (Also prints `bo01 size` + md5 per tag.)
2. **Or pull the files** from SD **partition 2** (ext4 rootfs): `/opt/npu-cap/out/` has
   `perax-bo01.bin`, `perax-coef.bin`, `pertensor-bo01.bin`, `pertensor-coef.bin`.

## What I do with it
Decode the perax coef: ABC header (`A = -M·(bias - in_zp·sw)`, B scalar, C per-channel mul) +
the float surface. **Decisive check:** does the perax float surface decode to the dequant weights
(derivable) while pertensor's stays a blob? If yes → write the per-axis `rkt_coefs.c` encoder to
reproduce these bytes, build libteflon, and the *following* flash tests it with the maxdiff oracle.

## Rebuild (if needed)
- per-axis model: `rkt2-venv/bin/python conv_perax.py work/c2d_perax.rknn`
- inject + image: debugfs `write` `run-coefcap.sh`→`/opt/npu-cap/run-capture.sh` (mode 0100755) +
  `work/c2d_perax.rknn`→`/opt/npu-cap/c2d_perax.rknn` into `rootfs-cap.ext2`, then
  `make-capture-image.sh`.
