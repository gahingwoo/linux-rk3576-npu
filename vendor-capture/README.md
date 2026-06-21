# Capture the working RK3576 vendor NPU command stream (path C1-B)

Goal: get the **vendor's known-good register command stream** for a conv on RK3576,
decoded in the same format as our rocket `regcmd` dump, so we can diff the exact CNA
start/CBUF sequence the vendor uses against what mesa emits — and find the one step
that makes the CNA executer actually engage.

This runs on the board using the **Radxa official RK3576 / ROCK 4D vendor image**
(working NPU). It only rebuilds the `rknpu.ko` kernel module, not a whole kernel.

## Steps

1. **Boot the Radxa official ROCK 4D vendor image** (vendor kernel + rknpu + NPU works).

2. **Get the matching kernel source/headers.** On the board (or a cross host), fetch
   the Radxa kernel that matches `uname -r` (Radxa's `rk-linux`/BSP branch for RK3576).
   The `rknpu` driver is at `drivers/rknpu/`.

3. **Apply the dump patch** to that kernel's `drivers/rknpu/rknpu_job.c`:
   - `patch -p1 < rknpu-regcmd-dump.patch`
   - If the context doesn't match, paste the added block by hand into
     `rknpu_job_subcore_commit_pc()` right after `first_task`/`last_task` are set and
     before the `pc_dma_ctrl` / `PC_DATA_ADDR` write. The added code is self-contained.

4. **Build just the module** against the running kernel:
   - `make -C /lib/modules/$(uname -r)/build M=$PWD/drivers/rknpu modules`
   - or in-tree: `make modules SUBDIRS=drivers/rknpu` (older) — produces `rknpu.ko`.

5. **Swap the module on the board:**
   - `rmmod rknpu` (stop any NPU users first), `insmod ./rknpu.ko`
   - or replace `/lib/modules/$(uname -r)/.../rknpu.ko` and reboot.

6. **Run one inference with the vendor runtime** (librknnrt + a model):
   - Any rknn demo that does a Conv2D, e.g. the rknn_model_zoo mobilenet demo, or a
     tiny single-conv `.rknn`. One invocation is enough.

7. **Capture the dump:**
   - `dmesg | grep "rknpu cap:" > /tmp/vendor-regcmd.txt`
   - Copy `/tmp/vendor-regcmd.txt` back here (drop it in this folder).

## What we do with it

Diff `vendor-regcmd.txt` against the mesa/rocket regcmd (our `dirty/log.txt`
`rocket dbg regcmd` full dump). Focus on, in order:
- the CNA (`tgt=0201`) S_POINTER / CBUF / DATA_SIZE / op_en sequence and ORDER,
- anything the vendor writes that mesa doesn't (a CNA start/flush/credit step),
- the target-0x81 broadcast and any 0x0041 control words around it.

That diff should reveal the RK3576-specific CNA-engage step that mesa is missing.

## Notes / fallbacks
- If `phys not linear-mappable`, change `phys_to_virt(phys)` to
  `memremap(phys, n*8, MEMREMAP_WB)` + `memunmap`.
- If the runtime uses multiple IOMMU domains and the dump shows a bad phys, try
  iterating `rknpu_dev->iommu_domains[0..iommu_domain_num-1]` for a non-zero
  `iommu_iova_to_phys`.
- Keep it to the FIRST job (the static `dumped` guard) so dmesg isn't flooded.
