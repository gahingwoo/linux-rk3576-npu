# Payload replay: rknn UABI vs rocket UABI (Tomeu's method)

Goal (from flipper #55): take the **exact** binary payload rknpu2 submits for the
simplest conv — input, weights/coefs, bias, output, cmdstream (regcmd) — and
replay those *same bytes* through both kernel UABIs. This removes the
quantization mismatch that blocked the build-both-and-diff approach: the weights
are now byte-identical because they're the *captured* vendor bytes, not a
re-quantized rebuild.

Plan:
1. **Capture** the vendor payload (rknn stack) → a set of files.
2. **Replay via the rknn UABI** (`/dev/rknpu`) on the vendor stack → must
   reproduce the captured output. Validates the captured payload + the replay
   program.
3. **Replay via the rocket UABI** (`/dev/accel/accel0`) on the mainline stack →
   if it fails with the *same* bytes that just worked through rknn, the bug is
   isolated to the rocket **kernel driver** (userspace ruled out).

## What to capture (the payload)

Per the regcmd's address registers (already known):
`0x1088` input · `0x1110` weights · `0x4018` output · `0x5020` bias.

- **regcmd** — the full register command stream (array of u64 `tgt/reg/val`).
  Length = `rknpu_task.regcfg_amount` entries.
- **input / weights / bias** — the full BO contents at the regcmd's addresses.
- **output** — the BO at `0x4018`, read **after** the job completes (expected
  result, for validation).
- **metadata** — task count, each BO's size, and the map {regcmd address field →
  which captured BO}, so the addresses can be re-patched on replay.

The one hard dependency in the bytes: the regcmd embeds **DMA addresses**
(0x1088/0x1110/0x4018/0x5020, plus the submit's regcmd self-address). On replay
the kernel hands us *different* DMA addresses for the freshly-created BOs, so the
replay must **patch** those fields in the regcmd to the new addresses before
submit. The capture records which address pointed at which BO; replay rewrites.

## rknn UABI (vendor, `/dev/rknpu` miscdev, magic 'r')

- `IOCTL_RKNPU_MEM_CREATE` (`struct rknpu_mem_create`): in `size/flags`; out
  `handle`, `dma_addr` (NPU address used in the regcmd), `obj_addr`.
- `IOCTL_RKNPU_MEM_MAP` (`handle` → `offset`) then `mmap(fd, offset)` → fill bytes.
- `IOCTL_RKNPU_MEM_SYNC` — cache sync around CPU access.
- `IOCTL_RKNPU_SUBMIT` (`struct rknpu_submit`): `task_obj_addr` = DMA addr of an
  array of `struct rknpu_task`; `subcore_task[core] = {task_start, task_number}`;
  `core_mask`, `iommu_domain_id`.
  - `struct rknpu_task`: `regcfg_amount`, `regcmd_addr` (DMA addr of the regcmd
    buffer), `enable_mask`, `int_mask`, `int_clear`.

Replay (rknn): create BOs for input/weights/bias/output/regcmd/task-array; fill
input/weights/bias/regcmd; patch the regcmd addresses to the new `dma_addr`s;
build the `rknpu_task` (regcmd_addr = regcmd BO dma_addr, regcfg_amount = N);
SUBMIT with task_number=1; sync + read the output BO; compare to captured output.

## rocket UABI (mainline, `/dev/accel/accel0`, DRM)

- `DRM_IOCTL_ROCKET_CREATE_BO` (`struct drm_rocket_create_bo`): in `size`; out
  `handle`, `dma_address`, `offset` (mmap). `mmap(fd, offset)` → fill.
- `DRM_IOCTL_ROCKET_PREP_BO` / `FINI_BO` — CPU-ownership cache sync.
- `DRM_IOCTL_ROCKET_SUBMIT` (`struct drm_rocket_submit`): `jobs[]`, each
  `drm_rocket_job` has `tasks[]` (`drm_rocket_task = {regcmd dma_addr,
  regcmd_count}`), `in_bo_handles[]` (input/weights/bias/regcmd),
  `out_bo_handles[]` (output).

Replay (rocket): CREATE_BO input/weights/bias/output/regcmd; fill + patch regcmd
addresses to the new `dma_address`s; SUBMIT one job, one task
(regcmd=regcmd_bo.dma_address, regcmd_count=N), in/out handles set; PREP_BO the
output; read + compare.

## Shared replay core

Both paths are the same five steps — create, fill, **patch regcmd addresses**,
submit, read-back — over different ioctls. `replay.c` detects the device
(`/dev/rknpu` → rknn, `/dev/accel/accel0` → rocket) and runs the matching path on
the same loaded payload files.

## Capture (produces the payload files replay.c reads)

Reuse the *already-validated* vendor-kernel reader (`rknpu_job.c`
`rknpu_cap_dump_bo` — the one whose input read back the exact ramp, so we know it
reads the right memory). Instead of a 2 KB serial head, copy each FULL BO into one
`vmalloc` capture buffer in a simple framed layout and expose it as
`/proc/rknpu_cap`:

    [magic "RKCAP1"] then per-section: [u32 tag][u32 len][bytes]
    tags: REGCMD, INPUT, WEIGHTS, BIAS, OUTPUT(post-complete)

On the board (no USB needed, same path as the diff capture):

    cat /proc/rknpu_cap | base64 > /dev/console     # ~250 KB -> ~340 KB, seconds

On the host, a tiny splitter decodes the base64 and writes
`regcmd.bin/input.bin/weights.bin/bias.bin/output.bin` + `meta.txt`
(`regcfg_amount`, `in_addr/wt_addr/out_addr/bs_addr/bs1_addr` from the regcmd
scan, and each BO size). That directory is what `replay.c` takes.

Alternative capture: an `LD_PRELOAD` shim over `ioctl()`/`mmap()` that records
`MEM_CREATE`/`MEM_MAP` and dumps the BOs on `SUBMIT` from userspace. Cleaner for
"exactly what userspace submitted," but more moving parts; the kernel-proc path
reuses code we've already proven reads the right buffers.

## File format (capture -> replay contract)

    regcmd.bin   the u64 register command stream (regcfg_amount * 8 bytes)
    input.bin    full input BO bytes
    weights.bin  full weights/coefs BO bytes
    bias.bin     full bias BO bytes
    output.bin   the vendor's computed output (expected result, for compare)
    meta.txt     regcfg_amount=, in_addr=, wt_addr=, out_addr=, bs_addr=,
                 bs1_addr= (vendor IOVAs from the regcmd), and *_size=

## Status

- `replay.c` — written from the UABI headers, cross-compiled for aarch64, both
  paths (rknn + rocket). **Not yet validated on hardware** — the ioctl flows are
  from the headers and need a board run to shake out subtleties (esp. rknn's
  `task_obj_addr` semantics and the rocket BO cache-prep ordering).
- capture (`/proc/rknpu_cap` full dump) — **next build**, reusing the validated
  reader.

## What the board run decides

- rknn replay reproduces the captured output → capture + program are sound.
- rocket replay with the identical bytes:
  - reproduces it → the rocket kernel path is fine; look further up (unlikely,
    given the mesa stack fails — would point at a config/firmware delta, cf.
    alchark's BL31/BL32 finding).
  - fails (degenerate output / wt_rd=0) → **isolated to the rocket kernel
    driver**, userspace and packing ruled out. This is the decisive split.
