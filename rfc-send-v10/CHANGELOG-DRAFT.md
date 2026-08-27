# v10 changelog — DRAFT, for the cover letter

⚠ This is the factual delta only. The cover-letter prose is yours; this is
here so nothing in it has to be recalled from memory. Every line below was
checked against the generated patches, not against notes.

## What changed since v9

**No code changed.** Every patch body is byte-identical to its v9 counterpart.
Verified by diffing each generated patch from `---` down, ignoring `index`
lines, the base-commit and the prerequisite-patch-id: 12 of 13 identical, and
the thirteenth differs only by the `Notes:` block described below.

### 1. The git note that v9's cover letter promised, and did not carry

v9 05/13 (`dt-bindings: npu: rockchip: add rockchip,rk3576-rknn-core`) now
carries the base/prerequisite note in the patch itself, which is what Rob's
bot asked for on v8.

⚠ **Igor's diagnosis was right and mine was not.** He wrote on 2026-08-25 that
"perhaps format-patch ran without --notes". `rfc-send-v9/send-v9.sh` never
passes `--notes`, and `grep -c '^Notes:' rfc-send-v9/v9-0005-*.patch` is 0.
The note is in the repository and always was; the flag was missing. The
rebase-loses-notes theory is unnecessary and unproven for this case.

`send-v10.sh` passes `--notes`, and the generated `v10-0005-*.patch` carries
the block. Checked, not assumed.

### 2. Six tags collected from the v9 review

| patch | tag |
|---|---|
| 02/13 wait for a running IRQ handler | Tested-by: Igor Paunovic # RK3588, three cores, induced reset, differential base, JOB_TIMEOUT_MS=2 |
| 03/13 let the core suspend after a reset | Tested-by: Igor Paunovic # RK3588, three cores, induced reset, JOB_TIMEOUT_MS=2 |
| 06/13 dt-bindings: power: allow resets | Acked-by: Conor Dooley |
| 07/13 dt-bindings: iommu: RK3576 NPU MMU | Acked-by: Conor Dooley |
| 08/13 pmdomain: power-on settle delay | Reviewed-by: Abel Vesa |
| 09/13 pmdomain: cycle resets on power-on | Reviewed-by: Abel Vesa |

Each was read back from lore verbatim before being applied, including the
address each reviewer signed with: Conor signs `conor.dooley@microchip.com`
though he posts from `conor@kernel.org`, and Abel signs
`abel.vesa@oss.qualcomm.com`. The two Tested-by comments are NOT the same
string; 02/13 carries "differential base" and 03/13 does not, which is how
Igor sent them.

### Tags carried forward from v9, all re-checked against lore

- 01/13 Tested-by: Igor Paunovic # RK3588, three cores
- 04/13 Reviewed-by: Igor Paunovic
- 05/13 Reviewed-by: Krzysztof Kozlowski (given on v7 02/10)

## What is worth saying in the prose, and what is not

**Worth saying:** Igor's differential run reproduced the silent race these
patches close. One inference in the unpatched arm signalled success with its
output buffer never written, all 48 channels 0x80, zero kernel messages, and
in 102 induced resets across nine runs it appeared only on the arm without
the patches.

**Not to claim:** that the note is there because notes were preserved across a
rebase. It is there because the flag is now passed.
