# Running the vendor's LLM runtime on this board

What r389 and r390 needed, kept here because none of it lives in a repository.

`~/Documents/kiln` is NOT a git repository and its vendor driver source is
FETCHED rather than vendored, so a change to it survives only as a patch here
and `driver/fetch-vendor-driver.sh` will overwrite the tree it applies to.

## The pieces

```
  driver     ~/Documents/kiln, Kiln's mainline port of vendor rknpu 0.9.8.
             Builds against this board's kernel in one command:
                 make -C <kernel tree> M=~/Documents/kiln modules
             ⚠ the rknpu.ko sitting in that directory is vermagic 7.1.3 and
             will not load on 7.2.0-rc5-next. Rebuild it.
  runtime    npu-refs/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/
             librkllmrt.so, version 1.3.0.
             ⚠ needs libgomp, which buildroot does not ship. This host is
             aarch64 so /usr/lib/aarch64-linux-gnu/libgomp.so.1 works, copied
             to a local directory first because the buildroot compiler wrapper
             refuses host library paths.
             ⚠ rkllm.h is C++ (<cstdint>): build with g++, not gcc.
  model      Llama-3.2-1B-Instruct-rk3576-w4a16.rkllm, md5 2d3962468e...,
             the same file charsiu's quality section scores.
  dts        rk3576-rock-4d-vendor.dts and -vendor786.dts in the board kernel
             tree: rocket's four nodes disabled, the vendor's three enabled.
```

🔑 **librkllmrt finds the NPU through the DRM render node**, which is why the
DRM_GEM path is the one to build. `/dev/dri/renderD128` appearing is the tell;
there is no `/dev/rknpu`.

## The trap that closed a door

`RKLLM_INFER_GET_LOGITS` is in their API and this model refuses it at every
sequence length from 64 to 544:

    meet unkown shape, op name: matmul_qk_rkllm_spilt_0, shape: 256, 64, 512

The model is exported for generation and the attention shapes a logits pass
needs are not in its compiled set. So the vendor-quality section cannot be
cross-checked against their real runtime this way, and that remains open.
