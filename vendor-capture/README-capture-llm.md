# The vendor LLM capture

## Why

charsiu now emits the vendor's exact int4 configuration. All 117 registers of
their `ic=2048 oc=1024` int4 op were diffed against ours and the five that
differed are settled: `0x3020` and `0x40b8` are the pair that makes the write
work, `0x100c` bit 29 and `0x1098` change nothing at all, and `0x3018` hangs the
block. And it still computes a bit pattern product rather than a weighted sum:
the effective weight for nibble v is `fp16bits(v)`, which spans 0 and the band
1.00 to 1.18, sixteen levels in eighteen percent of range.

So the difference is not in the stream. It is in what the stream points at, and
that is what this captures.

## What it does

`capture.so` is an `ioctl` interposer, 122 lines, from `kiln/capture`. It
records every buffer the runtime creates and, on the first submit, writes the
submit struct, the task array and every buffer to `/rknpu_replay`. It does not
know or care which runtime is above it, which is why the vision tool works
unchanged under the LLM one.

The image boots the VENDOR kernel with the vendor rknpu driver built in, runs
`llm_demo` from `librkllmrt.so` on the same Llama-3.2-1B the rest of this work
uses, and puts the dump on the console.

## Build and run

    ./vendor-capture/make-cap-rootfs.sh      # unprivileged, mke2fs -d
    ./vendor-capture/make-capture-image.sh   # -> images/sdcard-cap.img

Flash `sdcard-cap.img`. It runs at boot and prints to the console.

⚠ It is a SEPARATE image from the normal round image, because the vendor model
is 1.3 GB and the gguf models are 2.7, and nobody wants to write 6 GB twice.
The capture rootfs drops `/opt/charsiu/models` for the same reason.

⚠ `S98mndump` is still in the capture rootfs and will run first. On the vendor
kernel there is no `/dev/accel/accel0`, so it prints "no accel device" and
exits. Harmless, just noise before the capture.

## What the analysis needs

The regcmd (which op, and its shape), the WEIGHT buffer, the INPUT buffer and
the OUTPUT buffer for one int4 op. We hold the same model on the host, so their
weight bytes plus their result is enough to say what value the hardware gives
each four bit code, which is the one thing the register diff cannot answer.
