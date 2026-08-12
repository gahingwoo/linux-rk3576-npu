# RK3576 NPU (rocket + Mesa Teflon): conv0 zero-output, complete findings


## 2026-08-12 rounds 99 to 101: the off-by-one is the REFERENCE, and a reading of mine is withdrawn

The instrument added in round 97 showed every model carrying a one sided
off-by-one population against the CPU reference, `mn_dw1` worst at 85.50
percent of interior pixels exact with all 56125 of its misses one count low.
It looked like a defect and it is not one.

Two candidates died offline, without a flash. The Q4 per-channel coefficient
cannot be it, because all four of these models are per-TENSOR quantised, so C
is 16 for every channel in all of them. The bias rescale cannot be it, because
the bias scale and `in_sc * wt_sc` agree to 3.6e-8.

Round 99 killed the seam theory with its own control: the rate is FLAT across
rows, 0.140 to 0.149 on every eighth, and three row windows instead of two came
back byte identical at 56125, with three OUT_CVT lines in the log to show the
knob reached.

**Then I got it wrong.** I modelled the requant offline against a reference
computed as `floor(acc * M + 0.5)`, concluded the depthwise path truncates
where the regular path rounds half up, and spent round 100 on DPU 0x4044, the
one bit that differs between them. It does nothing: `mn_dw1` with the bit set
is byte identical to `mn_dw1` without it, and `conv2d-cal` with the bit
CLEARED is byte identical to `conv2d-cal` with it set, against a control that
predicted a drop to 75 percent. A clean negative, and the only luck in it is
that the bit was inert; had it moved anything I would have shipped a wrong fix
on a wrong model.

Round 101 stopped guessing at bits and printed raw values at fixed
coordinates instead, so the map could be solved. `mn_dw1` channel 4, where the
nine centred taps sum to zero so the ramp's linear part cancels and the
accumulator is constant at 217 between the wraps of the input modulus:

```
acc 217   exact 217 * 0.292199134827 = 63.4072   npu 63   reference 64
```

The hardware is right and the reference is not. tflite's requant is
`SaturatingRoundingDoublingHighMul` then `RoundingDivideByPOT`, and for this
multiplier its shift is -1, so the final divide is by two: `217 * q / 2^31` is
126.814, rounds to 127, and 127 / 2 is exactly 63.5, which rounds up. Two
roundings, and the second one lands on a half.

Emulating that exactly, offline, reproduces the board to the pixel:

| model | tflite shift | predicted vs board | hardware vs exact arithmetic |
|---|---|---|---|
| `mn_dw1` | -1 | 85.50%, 56125, all low / **85.50%, 56125, all low** | 99.97% |
| `mn_dw25` | -2 | 99.66%, 86 / **99.66%, 86** | 99.99% |
| `mn_conv0` | -7 | 99.80%, 773 / **99.80%, 773** | 99.98% |
| `conv2d-cal` | -10 | 100.00%, 9 / **99.99%, 10** | 99.98% |

So the hardware rounds half up on every path including depthwise, and is within
one count of exact real arithmetic everywhere. There is nothing to fix, and
`maxdiff <= 1` was the right pass mark all along. perch.py now says so at the
print, so the figure is read as a change detector rather than a defect.


## 2026-08-12 rounds 94 to 98: **conv0 is finished, 32 of 32.** The right pad does not work

What was left of conv0 after round 88 was one column. Not a scatter of rounding
noise, and not the saturation boundary: output column 111, 2058 of the 12544
pixels in a channel off by up to 255, with every other column, both rows and
the whole interior within one count.

Round 92's log had already said so and it was misread. `maxdiff excluding the
outer ring: 1, whole surface: 255` puts every large error on the ring; the
`rows with any error: 112/112` counter next to it fires on a difference of one,
which the rounding gives nearly everywhere, so it cannot tell a ring from a
surface and never disagreed. perch.py now prints each of the four edges and the
interior separately, and that is what named the column.

With tflite SAME on a 224 wide image at stride 2 the single pad lands after the
image, so column 111 is the only output column that reads a padded tap, and
`kx = 2` is the only tap that reaches it. Independently, an impulse model with
one live tap per channel and the real bias failed exactly the channels whose
tap has `kx = 2`, and the same taps with no bias passed, because the bias is
what lifts the fault clear of the ReLU clip. Same column, two ways.

**The padded tap is fed a raw zero, before the per lane values are applied.**
The measurement that shows it is a single-tap model at `kx = 2`, where columns
0 to 110 read a real pixel and column 111 reads the pad:

| CNA `0x1054/8/c` | interior | last column |
|---|---|---|
| `0xffffff80`, the captured value | 0 pixels off by more than 1 | 2122 |
| `0` | 346120 | **0, maxdiff 0** |

The two halves swap. `-128` is what an input zero point of 128 requires for
real pixels, and it turns the pad into `-128 * w` instead of nothing.

**Nothing steers that byte**, and the search for a register that does is now
closed with four negatives, each with a control that bit:

| swept | result |
|---|---|
| `0x1084` over `0x00`, `0x40`, `0x80`, `0x80808080` | only the row pad and column 0 move; the last column sits at 2122, 2128, 2128, 2129 |
| `0x1060`, two values | byte identical to the default |
| `0x1080` trailing width field to 0 | the whole surface collapses, interior exact 0.30 percent |
| `0x1080` trailing height field to 0 | byte identical to the default |

So one of the two trailing pad fields is load bearing and the other changes
nothing at all.

**The fix is to not ask for it.** Widen the input in memory to the first whole
number of feature atomics past what the last window reads, fill the added
columns with the input zero point, and tell the CNA the image is that wide. For
224 that is 240: `240 * 3` is a round 45 of the 16 byte units and the `0x1044`
low field stays at the 15 it already held. Six registers carry the width and
each reproduces its old literal exactly at 224, which is how they were
identified. `0x1080` is left alone; the pad is still requested, it simply stops
being reached.

| model | before | after |
|---|---|---|
| `mn_conv0` | 9/32, last column 2058 off by more than 1 | **32/32**, every edge and the interior within 1 |
| `fc_kx2` | 13/32, last column 2122 | **32/32**, last column maxdiff 0 |
| `fc_impb` | 26/32 | **32/32** |
| `conv2d-cal`, `mn_dw1`, `mn_dw25` | unchanged | unchanged |

`ROCKET_FC_WIDE=0` restores the narrow input and reproduces 2122 and 2058
exactly. Pinning either of the two least certain derived registers back to its
captured literal destroys the result, `0x1078` to interior 0.52 percent and
`0x118c` to 38.5 percent, so both derivations are load bearing.

**Two void tests on the way, and both were avoidable.** Round 96 asked whether
the trailing pad fields are honoured by setting them to 2; column 111 reads
exactly one pad column and row 111 one pad row, so a second one that nothing
ever reads cannot change any output, and both came back byte identical. The
question needed the pad taken away, not added. Round 95's whole premise, that
the pad byte is a raw input byte and should be `in_zp`, was refuted by its own
control: an already exact model broke on its last ROW when the byte changed.

**What the off-by-one population turned out to be.** "Within one count" has
been the pass mark since the first round, so a surface uniformly one low scored
the same as an exact one and nothing had ever looked at the sign. It is one
sided: conv0 773 pixels all low, `mn_dw1` 56125 all low, `conv2d-cal` 10 the
other way. Both emitters took the 15 bit OUT_CVT multiplier as
`((fui(M) >> 9) & 0x7fff) + 1`, always up. Round to nearest emitted the same
value on every model measured and truncation was worse, 99.95 against 99.99
percent, so rounding up is right and to nearest is now the default as the more
defensible of two answers that have never differed. `mn_dw1`'s 85.50 percent
interior exact, all one way, is a separate and much larger residual on the
generic path.


## 2026-08-11 rounds 76 to 88: **conv0 goes from an empty MAC to 99.5 percent pixel-exact.** Four literals

conv0 had never worked, in any log going back to 2026-08-08, and it was never
in the regression set, so round 76 was the first time anyone measured it. It
takes its own code path, `fill_regcmd_firstconv`, whose values are literals
taken from one capture. Four of them were wrong, each found by a different
instrument and each with a control that reproduces it:

| what | was | is | how it was found |
|---|---|---|---|
| the coefficient region | the fp16 scale table | left zero for a first conv | `0x5024` points at `bias_addr + 0x100`, and `rkt_coef_table_bytes()` is 256 for 32 channels, so round 52 wrote the table exactly on top of the operand |
| `0x1080`, padding amounts | `0x00000101`, symmetric 1 | derived from the task | an impulse decoded to the input shifted one pixel up and left, on all 32 channels at correlation 1.000 |
| `0x1084`, pad value | `0x00808080` | `in_zp - 0x80` replicated | derived; affects one row and one column here, too little for this measurement to resolve |
| `0x40ac/b0/b4`, requant | offset -2, `0x5391`, shift 25 | `out_zp - 0x80`, `0x76be`, shift 26 | an affine fit over unclipped pixels, validated by halving the multiplier three times |

**The requant is the one to read twice.** The comment above those literals said
computing them gives offset -128, scale `0x76be` and shift 22, "which is wrong
for conv0". The offset and the scale were right and the shift was short by
four; reading the three together as one captured triple is what kept conv0
broken. The four bits are presumably the CNA CVT this path enables, `0x104c` =
`0x4000` against the generic path's bypass.

The fit that found it had to be repaired first. Fitted over the whole surface
it read correlation 0.89, because the reference is ReLU-clipped and both
surfaces saturate, so a line between two differently clipped shapes cannot
reach 1. Excluding clipped pixels took it to 0.9999, and then `a` was identical
across all 32 channels and **doubled with every halving of the multiplier**,
which is what makes it a ratio rather than a number that happens to fit.

**Where it stands.** An impulse first conv is byte exact, 32 of 32 COMPUTED.
`mn_conv0` with its real weights is 99.5 percent of pixels exact, and what
remains is at the saturation boundary plus a 0.3 percent tail. `ROCKET_CVT_DOWN`
does not touch it, so it is not the int32 overflow the generic path carries that
knob for.

**Two readings of mine were withdrawn on the way**, both because a measurement
was taken in a state that could not answer:

- Round 77 swept the requant with an EMPTY MAC, saw nothing move, and concluded
  the requant was innocent. An output of `128 + offset` cannot respond to a
  requant sweep. The sweep proved the MAC was empty and nothing else.
- Round 83 saw the decode report 1.000 on an interior crop while the whole
  surface fit read 0.89, and called it a border error. With `pad_top` and
  `pad_left` at 0 the padding touches one row and one column, 1.8 percent of
  the surface, which cannot move a correlation that far. It was the clipping.


## 2026-08-11 round 74 RESULT: **DEPTHWISE IS DONE.** DPU 0x4050's depthwise value is not a constant

| model | result |
|---|---|
| `mn_dw25`, 7x7 x 1024 | **1024/1024** |
| `dw25_t4` / `dw25_t0` / `dw25_imp` | **1024/1024, every one COMPUTED** |
| `mn_dw1`, `dw1_t4`, `dw_imp`, 32 ch | 32/32, unchanged |
| `conv2d-cal`, `cal_oc16`, whole model | 128/128, 16/16, 2/2 |
| control: old constant `0x00013133` | **992/1024, live 0..991** |

`DPU 0x4050`'s `SIZE_E_2` field, bits 10 to 8, counts 16-channel atomics:

| channels | 16 | 32 | 48 | 64 | 80 | 96 | 112 | 128 | 256 | 1024 |
|---|---|---|---|---|---|---|---|---|---|---|
| SIZE_E_2 | 0 | 1 | 2 | 3 | 0 | 1 | 2 | 3 | 3 | 3 |

```
SIZE_E_2 = (DIV_ROUND_UP(oc, 16) - 1) & 3
```

Seven points were fitted and **three were predicted before being compiled**: 16
and 80 give 0, a value none of the fitted points showed, and 112 gives 2. Ten
of ten. mesa hardcoded `0x00013133`, the 32 channel case, and every depthwise
in this project has 32 channels except the one that did not work.

**A workaround was found first and thrown away.** Adding 1 to the packed
channel field of `DPU 0x4030` also closes the tail, and splitting the four
channel-count registers showed it is the only one that does. But the vendor
writes `oc-1` there at every channel count, 0x001f0310 through 0x03ff0310, and
mesa already matched. So it disagreed with the vendor and was masking `0x4050`.
It is gone. This project shipped a constant fitted to one capture before, in
`CNA 0x1080`, and it stood wrong for months.

**Three separate bugs were behind depthwise**, all found in two days:

| | |
|---|---|
| the coefficient record | 48 bytes, `[A|C]` and no B, twice as many records as a regular conv, fp16 table after it |
| the row window staging | a window overlapping the previous one by a row staged those rows a **second** time, so everything after the overlap convolved input two rows late |
| the weight buffer, and `0x4050` | channel **groups of 64**, not one group of C, and `SIZE_E_2` derived rather than hardcoded |

**Still open**: chained operations, and MobileNet, which needs them.


## 2026-08-11 round 69 RESULT: **THE 1024 CHANNEL DEPTHWISE COMPUTES.** The weight buffer is channel groups of 64

| model | before | after |
|---|---|---|
| `mn_dw25` (7x7, 1024 ch) | 432/1024, **2** COMPUTED | **992/1024, 413 COMPUTED** |
| `dw25_t4` / `dw25_t0` / `dw25_imp` | 0 to 112 / 1024 | **992/1024, every one COMPUTED** |
| live channels, one tap everywhere | 448..575 | **0..991, one run** |
| `mn_dw1`, `dw1_t4`, `conv2d-cal` | correct | unchanged, whole model 2/2 |

**The control passes**: `ROCKET_DW_GROUP=1024` reproduces the old numbers
exactly, 432/1024 with 2 COMPUTED and the same 448..575 window.

**The bug.** The depthwise weight buffer is **channel groups of 64**, each group
tap major inside itself and the groups laid end to end. mesa wrote one group of
C. A group of C puts a channel's nine taps `2C` bytes apart, 2048 at 1024
channels; a group of 64 puts them 128 apart whatever C is. **The two are
identical up to 64 channels**, which is why every depthwise in this project had
been byte exact and this one had not.

**How the board found it.** Nine models, each with the live tap at the same
position in every channel, gave nine contiguous live runs that moved with the
tap:

| tap | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| from | 0 | 64 | 192 | 320 | 448 | 512 | 640 | 768 | 896 |
| to | 127 | 255 | 383 | 511 | 575 | 703 | 831 | 959 | 991 |

Inverted: **each output channel could reach only one or two of its nine spatial
blocks**, advancing one tap every 128 channels. A depthwise needs all nine.

**How the layout was settled: offline, no board.** The depthwise weights are in
the `.rknn` even though the coefficient table is not, so vendor models were
compiled at 32, 128, 256 and 1024 channels with weights generated on the host,
which makes the comparison exact rather than a correlation:

| layout | 32 ch | 128 ch | 256 ch | 1024 ch |
|---|---|---|---|---|
| **channel groups of 64** | 288/288 | **1152/1152** | **2304/2304** | **9208/9216** |
| one group of C (mesa's) | 288/288 | 4/1152 | 15/2304 | 367/9216 |

The eight lanes that miss at 1024 are all **one channel**, whose kernel the
quantiser treated differently; 1023 of 1024 channels are exact.

The total size does not change, 16 groups of 9 x 128 being the same 18432
bytes, so the CNA weight byte count at `0x101c` is untouched.

**Still open**: channels 992..1023 are constant in all three 1024 channel
models, exactly 32 of them, in a layer of 16 whole groups. Not a partial group.

**Withdrawn along the way**: round 63's reading that the hardware used tap
`(-p) mod 9`. Writing that permutation made things worse, and round 65 showed
why: the tap the decoder reports for a channel whose output is wrong is
meaningless, spread flat across all nine offsets, while the 32 channel control
resolves every channel to offset 0.


## 2026-08-11 round 62 RESULT: **DEPTHWISE IS SOLVED.** The overlap rows were staged twice

| model | before | after |
|---|---|---|
| `dw_imp` (impulse, 112x112x32) | 0/32 | **32/32, all COMPUTED** |
| `mn_dw1` (112x112x32) | 9/32 match, 1 COMPUTED | **32/32 match, 23 COMPUTED** |
| row maxdiff profile, every 8th row | `1 x12, 200, 200` | **`1` everywhere** |
| seam moved to 46, and to 64 | — | **32/32 both** |
| `conv2d-cal`, `cal_k3` | 128/128 | 128/128, whole model 2/2 |

`mn_dw1`'s other 9 channels are trivial because the reference is genuinely
constant on them, so **every channel is right**.

**The control passes**: `ROCKET_STAGE_ALL=1` reproduces the old broken profile
exactly, `1 x12, 200, 200` on `dw_imp` and `255, 255` on `mn_dw1`. And the fix
is not tuned to one boundary: moving the seam to 46 rows (three windows) and to
64 (two) still gives 32/32.

**The bug.** A row window overlaps the one before it by one row on each side,
and those rows are already in the CBUF. `rkt_regcmd` already pointed the reuse
base at them correctly (`0x103c` = `56 x 89`). `rkt_split_tasks` staged them
*again*, which writes them a second time at the next free CBUF row, so every
row after the overlap sat two rows late and the window convolved shifted input.

The vendor's capture of this exact layer writes **two different row counts**
for its second window where mesa wrote one:

| register | vendor | means | mesa was |
|---|---|---|---|
| `0x102c` | 23 | rows the window **spans** | 23, correct |
| `0x1028` | 21 (`56 x 21`) | rows it **stages** | 23, wrong |
| `0x1078` | 21 | the same | 23, wrong |
| `0x1098` | 21 (`112 x 21`) | the same | 23, wrong |

**Why this hid for so long**: every regular model in this project is 80x80 or
smaller and takes the single-task path, so nothing that tiles was ever correct
and nothing that was correct ever tiled. Every coefficient sweep came back flat
because the coefficients were already right.

**Still open**: `mn_dw25`, 7x7 with 1024 channels, is unchanged at 2 COMPUTED
of 1024. It is a single window, so this fix does not touch it, and it is now
clearly a different bug.


## 2026-08-11 round 54, offline: THE DEPTHWISE COEFFICIENT TABLE EXISTS, and it is decoded

**The claim this replaces.** Two earlier readings concluded the vendor emits no
per-channel coefficient table for a depthwise layer. Both searched the `.rknn`.
**It is not in the `.rknn`: librknnrt builds it at load time**, which is why a
full-file sweep of the model file, two structural oracles and three readings of
the weight buffer all came back empty. The runtime capture has it in plain
sight, and this is the first time the capture's address registers were resolved
into the captured buffers rather than read as opaque values.

**Resolving the address registers** (`sv_addrmap.py`) for `sv_dwu`, the
depthwise half of the single-variable pair:

| register | resolves to | what is there |
|---|---|---|
| CNA `0x1110` | `bo1+0x0000` | the 576 byte weight buffer |
| RDMA `0x5020` | `bo1+0x0240` | immediately past it |
| RDMA `0x5024` | `bo1+0x0400` | `0x0E0E`, the four byte operand |

so the per-channel region is exactly 448 bytes, for 32 output channels. The
regular conv in the same capture has the same shape of thing with a delta of
320. Taking 64 bytes of fp16 off each leaves **256 and 384**.

**What the 384 bytes are** (`dwcoef_rec48.py`): eight records of 48 bytes,

```
A   8 x int32   at +0
C   8 x int16   at +32
(no B)
```

in plain channel order, records four to seven zero, against the regular conv's
four records of `[A|B|C]` in 64. Nothing here is fitted. Both models were
compiled from weights and biases generated in `sv_pairs.py`, and the
calibration set is generated too, so `in_scale` and `in_zp` are known:

| term | formula | control (regular) | depthwise |
|---|---|---|---|
| C | `round(0x4000 * wt_sc[oc] / max wt_sc)` | 32/32 exact | 32/32 exact |
| A | `round(bias/(in_sc*wt_sc[oc])) + (in_zp-0x80)*(N*wt_zp[oc] - sum(w_q))` | **32/32 exact** | **32/32 exact** |
| fp16 table | `wt_sc[oc]` | corr 0.999997, ratio 1.00001 | corr 1.000000, ratio 0.99994 |
| B (regular only) | `-wt_zp[oc]` | 32/32 exact | absent |

**A needed no change.** `calculate_weight_sum()` already returns
`sum(w_q - wt_zp)`, so the derived expression IS `bias - (in_zp - 0x80) * sw`,
which this driver has written all along. What was wrong was the record shape,
the record count, and where the fp16 table and the `0x5024` operand land after
it. **Three things at once, which is why changing any one of them never moved
anything.** `ROCKET_DW_REC48` in rounds past changed the record and left the
`0x5024` pointer inside the table it had just resized.

**The weight buffer is not the bug.** mesa's RK3576 depthwise packing
reproduces the vendor's 576 bytes: **288 of 288 weight lanes** under the
ky-major plane order it uses, 96 of 288 under the transpose. The two bytes after
each channel pair, which this file called padding, are the **negated
per-channel weight zero point**, identical in every spatial block, the same
quantity and the same sign a regular conv carries as B. Every model here is
per-axis quantised so that zero point is zero and the sign was never visible;
it is corrected anyway.

**The single-variable register diff**, the thing round 42 could not do because
`g_dw1` and `g_k3s1` differed in three ways: `sv_rgu` and `sv_dwu` differ in
`groups` alone, and **14 value registers move**, identically in all six tasks.
`rkt_regcmd.c` already emits the vendor's value for every one of them. The
register stream is not the bug either.

**Also settled**: the toolkit quantises conv weights **per output channel and
asymmetrically**, min and max of the channel onto the 256 codes. That
reproduces the stored bytes of the regular conv as a multiset, 9216 of 9216,
where symmetric `/127` reaches 89.7 percent. The stored order is a shuffle, not
OIHW, which is expected of a hardware layout.

**The one thing 32 channels cannot pin**: eight records for 32 channels is
either twice the regular grouping or a padding of the channel count to 64, and
this geometry gives eight either way. The doubling is what shipped, because it
is the doubling this driver already applies to the depthwise channel atomic.
`ROCKET_DW_RECS` overrides it so the board can decide.

**numpy started dying with SIGILL** in its own `_sanity_check` on this VM;
the bundled OpenBLAS picks a kernel the guest traps on. Pinned with a `.pth` in
the venv setting `OPENBLAS_CORETYPE=ARMV8`. Nothing to do with the NPU, but it
stops every offline script in this repo.


## 2026-08-09 round 28, offline (The coefficient buffer is stored in the .rknn, so this stopped needing a board. The region at `groups*64` is a per-channel fp16 weight scale table. Rounds 26 and 27 were reading toolkit noise.)

The vendor's coefficient buffer is not synthesised at load time. Mapping the
8192 bytes captured from the board back into `g_cal_rk3576.rknn` puts every
model-dependent part of it in four contiguous chunks of the model file, each
behind an exact uint32 length prefix:

| coefficient buffer | .rknn offset | size |
|---|---|---|
| `0x000..0x400`, the A/B/C table | `0x8540` | 1024 |
| `0x400..0x500`, 2 bytes per output channel | `0x37c0` | 256 |
| `0x500..0x700` | `0x81c0` | 512 |
| `0x700..0x0b00` | `0x7d80` | 1024 |

`rknn_blobs.py` pulls them out and checks itself against that capture on every
run. So "what does the vendor put here" became a host question: compile a model,
read the bytes.

**The control that should have been run first, and now was.** Compiling ONE
identical model twice:

| chunk | stable across a recompile |
|---|---|
| `0x000..0x400` A/B/C | **1024/1024** |
| `0x400..0x500` | **256/256** |
| `0x500..0x700` | 16/512 |
| `0x700..0x0b00` | 33/1024 |

**So `0x500..0x0b90` is not reproducible.** The toolkit writes different
content there on every build of the same model: about 46% zeros and the rest
reading as leftover float data. **Rounds 26 and 27 measured that.** The "1682 of
1936 bytes differ" and the "k=5 sparse, k=3 dense" block structure were compile
to compile noise, not a property of any model. Both are withdrawn.

**What the reproducible part depends on**, each pair differing in exactly one
thing (`sv_pairs.py`, `sv_compare.py`):

| pair | A/B/C | the 2-bytes-per-channel table |
|---|---|---|
| same model twice (control) | identical | identical |
| different weights | 856/1024 differ | 227/256 differ |
| **5x5 with a zero ring vs the 3x3 it contains, same weights** | **identical** | **identical** |
| 128 channels vs 64, shared weights | first 512 B identical | first 128 B identical |

The kernel pair is the one that was designed to be readable: the 5x5 model's
weights are zero outside the centre 3x3 and equal to the 3x3 model's inside it,
so both compute the same function, both quantize the shared taps to the same
bytes, and only k moves. **Nothing in this buffer depends on the kernel size.**

**What the table is.** Read as fp16 the entries are each channel's weight scale.
Not asserted from the magnitude agreeing, which was only good to about 7%, but
from moving one channel (`sv_scaleprobe.py`): multiply channel 7's weights by 2
and channel 11's by 1/2, recompile, and

```
entries that changed: [7, 11]
  channel   7: 0.0018549  -> 0.00370979   ratio 2.0000
  channel  11: 0.00193024 -> 0.000965118  ratio 0.5000
  untouched channels that moved anyway: 0
```

**This is one fp16 per output channel, at `groups*64`, which for oc=128 is
exactly `0x400`.** `rkt_coefs.c` writes a float32 dequantised weight surface
there instead, `MAX2(ic*oc*k*k, 8192)` entries, 204800 bytes for conv2d-cal.
Same address, wrong element type, wrong length, wrong meaning.

It also explains round 27 without any appeal to kernel size: zeroing from
`0x400` killed conv2d-cal because the float32 weights landing there were being
read as fp16 pairs and happened to be nonzero, and zero scales every channel to
nothing.

**Round 28 ships that**: `oc` fp16 values at `groups*64` and nothing after them,
with `ROCKET_FS_FLOATS` restoring the old surface, `ROCKET_FS_REL` writing the
scale relative to the largest channel, and `ROCKET_FS_ZERO` as the control that
must fail. Built, not flashed.

The k=5 versus k=3 divide is **not in the coefficient buffer**. That is the
main thing this round changes about where to look next: it is in the weight
buffer layout or in the registers.

Deploy path, learned the hard way: copying `libteflon.so` into
`buildroot/br-out/target/` does nothing, the rootfs build overwrites it from
`rootfs-overlay/usr/lib/libteflon.so`. Verify by dumping the file back out of
`images/rootfs.ext2` and grepping it for the knob names.

## 2026-08-10 the fp16 table is PROPORTIONAL to the weight scale, not equal to it

Using the table's value as the per-channel quantisation scale on the known
weights gives a range of **[-214, 191]**, which overflows int8 by 1.68x. So the
entries are proportional to the weight scale, not the weight scale itself, and
the "+0.998 against the scale implied by A" match says only that both are
proportional to the same thing, since A's implied scale was derived from the
same relation.

That qualifies the round 52 reading. The table's **position and element type**
are established, and writing `weight_tensor->scales` there passes every working
shape, but the exact quantity is off by a constant factor of roughly 1.68 in the
vendor's own model. Whether mesa's version is right or merely inside a tolerant
range is not established, and the passing shapes cannot distinguish those.

The depthwise weight buffer still does not decode under it either: as int8 the
multiset overlap with the 288 quantised weights is 41%, near chance; as int16 it
is 0%; and per-channel 18-byte blocks match 0 of 32.

So the remaining unknowns are now three, and the first is new:

1. the constant factor between the fp16 table and the weight scale,
2. the four-byte operand, `0x1004` for mesa against `0x0E0E` for the vendor,
3. depthwise, which the whole coefficient chain does not touch.

## 2026-08-10 round 53 RESULT: the derived layout is in, with no regressions

| model | new default | old arrangement |
|---|---|---|
| conv2d-cal | **128/128** | 128/128 |
| cal_k3 | **128/128** | 128/128 |
| cal_k1 | **128/128** | |
| cal_s1 | **128/128** | |
| cal_oc16 | **16/16** | |
| mn_pw2 | **64/64** | |
| conv2d-cal, whole model | **2/2 OK**, relu maxdiff 1 | |
| dwconv, mn_dw1 | unchanged, as expected | |

The control passes, so round 52's comparison was what it looked like, and every
shape that worked before still works. **The vendor's coefficient layout is the
default and nothing regressed.**

Where that leaves the surface:

```
0x5020 -> [A/B/C table]              A = bias_q - (in_zp - 0x80)*sw, verified
                                     B = 0x80 - wt_zp, verified
                                     C = 0x4000 * s_c / max(s_c), verified
          [oc x fp16 weight scale]   derived from weight_tensor->scales
0x5024 -> operand                    four bytes, still a constant
```

Two things remain, and both are now sharply stated rather than diffuse:

1. **The four-byte operand.** mesa needs `0x1004` and the vendor writes
   `0x0E0E`, and each fails in the other's configuration. `0x13d3` is in the
   right fp16 magnitude range and still fails, so magnitude alone does not
   explain it and the round 36 bit pattern is doing real work under mesa's
   configuration.
2. **Depthwise.** Unmoved by the entire coefficient chain: the 48-byte record,
   the fp16 table, the float bias, per-channel B, six different operand words
   and the old float surface all leave it at 6 distinct values. Whatever is
   wrong is not in this buffer.

## 2026-08-10 round 53 (Lock it in: the vendor's layout becomes the default)

mesa now writes, with no knobs set:

```
0x5020 -> [A/B/C table][oc x fp16 weight scale]
0x5024 -> the operand, four bytes
```

instead of a lone constant sitting where the scale table belongs. Everything
there is derived from the model except those four bytes.

`ROCKET_SCALE_OFF` restores the previous arrangement and is the control in round
53: it has to still pass, or round 52's comparison was not what it looked like.
`ROCKET_SCALE_MUL` writes the requant multiplier instead of the weight scale and
`ROCKET_OP2` overrides the operand, so both alternatives stay reproducible.

Round 53 runs every shape that already worked, on the new default and on the old
path, plus depthwise where nothing is expected to change. Built, not flashed.

## 2026-08-10 round 52 THE LAYOUT IS ADOPTED (the vendor's arrangement works in mesa, and the magic word shrinks to one operand slot)

Baselines 128/128 at both ends.

| | channels |
|---|---|
| **fp16 weight-scale table, pointer moved past it, operand `0x1004`** | **conv2d-cal 128/128, cal_k3 128/128, cal_k1 128/128** |
| the same with the vendor's `0x0E0E` as the operand | 0/128, as it must |
| dwconv | 0/16, distinct 6, unchanged |

**Every failure from rounds 46 to 51 had one cause**: each time the pointer
moved, the new target was given the vendor's `0x0E0E`, and round 49 had already
shown that word alone empties the convolution under mesa's configuration.
Content, layout and operand value were tangled together across six rounds.
Separated, the layout passes immediately.

mesa's surface is now the vendor's:

```
0x5020 -> [A/B/C table]              A, B and C all checked against the capture
          [oc x fp16 weight scale]   a derived table where there was nothing
0x5024 -> operand                    the only constant left, four bytes
```

The A/B/C formulas are verified: A is `bias_q - (in_zp - 0x80)*sw` and matches
the capture at 128 x swq once the int8-versus-uint8 input zero point is
accounted for, B is `0x80 - wt_zp` and the vendor's per-channel variant cannot
arise under tflite, C is `0x4000 * s_c / max(s_c)`. The fp16 scale table is
derived from `weight_tensor->scales`.

**So the magic word is now isolated to a single four-byte operand slot** rather
than living inside the scale table. That is also why it looked like a bitfield
for six rounds: the sweep was writing into an operand, not a scale.

Still unexplained: why that operand is `0x1004` for mesa and `0x0E0E` for the
vendor. And depthwise is untouched by any of this, 6 distinct values exactly as
at baseline, so its cause remains elsewhere.

## 2026-08-10 round 51 (The vendor's arrangement fails too, and the two failures have one cause)

Baselines 128/128 at both ends.

| | distinct |
|---|---|
| weight scale in the table, pointer moved | 1, empty |
| the requant multiplier with the pointer, for contrast | 1, empty |
| dwconv, vendor arrangement | 21, still 0/16 |

Both combinations fail identically, so the decision rule's second branch
applies: **the table content is not the issue.**

But it is not the pointer move either, and the two failures have one cause.
When the pointer moves, the new target gets `0x0E0E`, the vendor's own operand
value, and round 49 already showed that exact word gives an empty convolution in
the slot mesa's `0x5024` already points at. Same word, same failure, once
written in place and once written at a moved pointer. The move was never tested
separately from the value.

Round 52 moves the pointer and keeps `0x1004`, the value mesa's configuration
demonstrably accepts, with `ROCKET_OP2=0x0E0E` beside it as the variant that
must fail. That separates the last two things still tangled together. Built,
not flashed.

## 2026-08-10 A confirmed exactly, and the untested combination identified

Using the **exact** per-channel scale from the captured fp16 table, rather than
the `max/127` approximation that misled several rounds:

```
A / swq   =  127.514 .. 133.650
fit       =  A = 127.993*swq + ...   max error 572 over a range of +-196872  (0.3%)
```

**A = 128 x swq**, which is mesa's own formula `A = bias_q - (in_zp - 0x80)*sw`
with `in_zp = 0`. rknn quantises its input as int8 with zero point 0, while
these tflite models are uint8 with zero point 128, so the weight-sum term is
present for the vendor and absent for mesa, and both are the same expression.

So the arithmetic is settled: **A agrees, B was closed last round, C is mesa's
formula.** What is left is the layout, and laying out what has actually been run
shows the combination that matters was never one of them:

| | table content | pointer |
|---|---|---|
| round 47 | weight scale | not moved |
| round 49 | requant multiplier | moved |
| **never run** | **weight scale** | **moved** |

The capture says the table holds the **weight scale**, since those entries match
the scale implied by A at +0.998. Round 49 moved the pointer with the wrong
content in the table; round 47 had the right content with the pointer still
aimed at it. Neither tested the vendor's actual arrangement.

Round 51 runs `ROCKET_SCALE_TABLE_WT` together with `ROCKET_SCALE_PTR`, with the
round 49 combination beside it for contrast. Built, not flashed.

## 2026-08-10 round 50 (VOID, and then closed properly: tflite per-axis forbids the very thing the vendor's B encodes)

Baselines 128/128. Per-channel B is harmless on the working shapes, all three
still 128/128, and changed **nothing** on dwconv, mn_dw1 or mn_pw24, every count
identical to baseline.

That is not a refutation, because the knob was a no-op. Checking the models
rather than assuming:

| model | scales | zero_points | distinct zero points |
|---|---|---|---|
| dwconv | 16, **per-axis** | 16 | **1**, all zero |
| mn_dw1 | 1 | 1 | 110 |
| mn_pw24 | 1 | 1 | 130 |
| conv2d-cal | 1 | 1 | 133 |

`dwconv` is genuinely per-axis in its scales, but all sixteen of its zero points
are 0, so `0x80 - zero_points[oc]` is 128 for every channel, exactly what the
scalar path already produced. The other three are per-tensor. **No model in the
suite could have shown a difference**, and I should have checked that before
spending a flash.

**And checking it closes the thread rather than leaving it open.** The tflite
spec requires per-axis quantisation to be symmetric, with a zero point of zero
on every channel. The vendor's B varies because rknn uses asymmetric
per-channel quantisation, which tflite does not permit. So the decode stands,
the vendor's B really is `0x80 - wt_zp[oc]` per channel, and it is **not
reproducible from a tflite model and does not need to be**: with per-axis zero
points pinned at 0, B is uniformly 128, which is what mesa's scalar path already
writes.

So this is a real difference between the two stacks that cannot be the cause of
mesa's depthwise failure, and the third difference is still unlocated.

## 2026-08-10 B is PER CHANNEL in the vendor, and mesa has never used the per-channel zero point

Round 49 said the difference is elsewhere in the surface. Decoding the vendor's
A/B/C table found it, in the one column nobody had looked at:

```
sv_rgu B column   26 distinct values over 32 channels, range -25 to 23, mean 0.16
                  correlates with NOTHING tested: bias, weight sum, A, C, wt_sc
mesa              B = 0x80 - wt_zp, ONE value for the entire layer
```

A tight spread centred on zero is exactly what `0x80 - wt_zp[oc]` looks like
when the per-channel zero points sit near 128, which is what an asymmetric uint8
quantiser produces. That it correlates with nothing else is the point: it is not
derived from the weights at all, it is a zero point.

**And the interface has carried this all along.** `pipe_tensor` has a
`zero_points` **array** beside `scales`, and `rkt_ml.c` already tests it to
decide whether a tensor is per-axis quantised. `rkt_coefs.c` has only ever read
the scalar `weight_tensor->zero_point`, in every place it needs a zero point.

`ROCKET_B_PERCH` uses `zero_points[oc]` when the array is present. Round 50
built, not flashed, running it on the shapes that work as a regression check and
on depthwise and `mn_pw24`, which are the per-channel quantised ones where a
missing per-channel zero point should show.

Not claimed: that this fixes depthwise. It is one missing term, found by
decoding rather than guessing, in a table whose other two columns are already
understood.

## 2026-08-10 round 49 (The vendor's own value produces an empty convolution in mesa. Same field, two configurations, two different acceptable contents.)

Baselines 128/128 at both ends.

| | distinct | range |
|---|---|---|
| baseline, `0x1004` | 128 | 128..255 |
| **`0x0E0E`, the vendor's own second-operand value** | **1** | **all 128**, empty |
| the full vendor layout | 1 | all 128 |
| **dwconv with `0x0E0E`** | **21** (baseline 6) | 0..128 |
| mn_dw1, full layout | 247 | 0..255 |

`0x0E0E & 0x3f` is `0x0E`, which violates the round 36 rule, and it produced
exactly what that rule predicts. So the rule holds for mesa and the vendor's own
value fails in mesa.

**The contradiction is now stated cleanly**: the vendor writes `0x0E0E` at its
`0x5024` target and computes; mesa writes `0x1004` at its `0x5024` target and
computes; swapping either way fails. One field, two configurations, two
disjoint sets of acceptable contents. So what differs is not this field's
content, and round 36's rule is a property of mesa's configuration, confirmed a
second time by a direct test rather than by inference.

The identification of the slot as the second operand still stands, since mesa's
`0x5024` demonstrably points at `groups*64`. What does not follow, and what
round 49 disproves, is that the vendor's content can simply be copied into it.

**The one consistent positive**: `dwconv` responds to this field every time.
Baseline 6 distinct values, 21 with `0x0E0E`, 28 with the scale table in round
47. Depthwise reads it and the regular shapes tolerate a wide range, which is
the opposite of how this looked when the field was thought to be a scale.

## 2026-08-10 the magic word slot IS the second operand, and round 46 left it empty

Putting the capture's layout beside mesa's answers what the round 36 rule
describes:

```
vendor   0x5020 -> [A/B/C table][oc x fp16 scales]
         0x5024 -> 0x0E0E, then zeros
mesa     0x5020 -> [A/B/C table]
         0x5024 -> groups*64          <- exactly where mesa writes the magic word
```

**mesa's `0x5024` points at `groups*64`, so the word this driver has been
sweeping since round 32 is the SECOND OPERAND, not a scale.** That resolves the
contradiction in round 48 without any special pleading: the vendor's fp16 scale
entries violate the round 36 rule in 30 of 32 because they are **a different
field**. The rule describes what mesa's second operand tolerates.

It also names round 46's mistake precisely. It wrote the scales and moved the
pointer past them, but **never wrote anything at the new target**, so the second
operand read zeros. Both halves were right and the round still failed.

Round 49 tests the cheap version first, and it needs no new code because
`ROCKET_FS_F0` already writes that exact word: put the vendor's own
second-operand value, `0x0E0E`, where mesa's `0x5024` already points, with no
layout change at all. Then the full vendor layout, scales at `groups*64`,
`0x0E0E` at `groups*64 + oc*2`, pointer moved there. Built, not flashed.

## 2026-08-10 round 48 (The requant-multiplier reading is WITHDRAWN, and the round 36 rule turns out not to be the hardware's format either)

Baselines 128/128 at both ends.

| | distinct | range |
|---|---|---|
| baseline, the magic word | 128 | 128..255 |
| **the derived multiplier** | **1** | **all 128**, an empty convolution |
| the weight scale | 129 | 0..128 |
| cal_k3, cal_k1 with the multiplier | 1 | all 128 |

**Why, and it is my own circularity**: `fp16(0.00095521)` is `0x13d3`, whose low
six bits are `0x13`, which **violates** the round 36 rule. And the "magnitude
window" I read off the passing set in round 48 was circular, because from round
35 onward **I only ever swept words I had constructed with low six bits `0x04`**:

```
0x1004 0x1044 0x2044 0x3fc4 0x0fc4 0x1a44 0x1a04 0x1a84   all  w & 0x3f == 0x04
```

A set selected for a bit pattern cannot be used to infer a magnitude range. So
the requant-multiplier reading is **withdrawn**; it explained the window, and the
window was an artifact of my own sweep.

**But the vendor settles what the rule actually is**, and it is not what round
36 thought. Checking the vendor's own 32 captured entries against it:

```
sv_dwu (depthwise)  low 6 bits == 0x04 for  0/32
sv_rgu (regular)    low 6 bits == 0x04 for  2/32     (chance is 0.5/32)
```

**The vendor violates the rule in essentially every entry and its models
compute.** So `(w & 0x3f) == 0x04` is not the hardware's format. It is a
property of *mesa's current configuration*: under whatever mesa is doing to that
surface, only those bit patterns happen to work, and `0x1004` works by
satisfying an artifact rather than by being correct.

That re-frames rounds 32 to 37. They characterised a symptom very precisely.
Chasing the right value for that slot while the rest of mesa's setup differs
from the vendor's is chasing the artifact, and the real difference is elsewhere
in the surface. `ROCKET_SCALE_PTR` alone also failed, so the pointer is not the
whole of it either.

## 2026-08-10 the slot holds the REQUANT MULTIPLIER, and the magic word finally has a meaning

Round 47 said the table failed and why: `conv2d-cal`'s weight scale is
`3.9125464`, whose fp16 is `0x43d3`, a value round 28 already proved fails. So
the slot is not the weight scale. Reading **every** word rounds 36 and 37 swept,
as fp16, gives the accepting window directly:

```
pass   0.000474  0.00049  0.000521  0.002937  0.003059  0.003181  0.008331
fail   0.00013 and below,  2.13 and above
```

and for `conv2d-cal`

```
in_sc * wt_sc / out_sc  =  0.0078125 * 3.9125464 / 32  =  0.00095521    INSIDE
wt_sc alone             =  3.9125464                   =  0x43d3, known to fail
```

**The slot holds the per-channel requant multiplier `in_sc * wt_sc[oc] /
out_sc`, as fp16.** Everything lines up on that and nothing lines up on the
weight scale:

- the magic word `0x1004` is `0.00049`, the same order as the real multiplier,
  which is why a single hand-swept constant worked at all;
- the vendor's captured entries are around `0.0012` for its own model;
- the "bitfield rule" from round 36 was the shape of fp16 values in that window;
- one word sufficed for `conv2d-cal` because it is per-tensor quantised, so
  every entry of the table is the same number;
- and `dwconv` moved in round 47, from 6 distinct values to 28, precisely
  because depthwise is per-channel and gets 32 different entries.

Round 48 writes it, with the weight-scale version kept behind
`ROCKET_SCALE_TABLE_WT` so round 47's failure can be reproduced side by side.
Built, not flashed.

## 2026-08-10 round 47 (Separated at last. Neither half is adoptable as written, but depthwise moved for the first time.)

Baselines 128/128 at both ends.

| | distinct | range |
|---|---|---|
| baseline | 128 | **128..255** |
| **TABLE alone** | 129 | **0..128** |
| PTR alone | 256 | 0..255 |
| both | 256 | 0..255 |
| **dwconv, TABLE alone** | **28** (baseline 6) | **0..245** (baseline 0..128) |

**Why TABLE alone fails, and it is not a mystery**: `conv2d-cal`'s
`weight_tensor->scale` is `3.9125464`, and `fp16(3.9125464)` is **`0x43d3`**,
which is exactly the value round 28 wrote and which failed then too. Writing
tflite's weight scale into that slot reproduces a known-bad round.

So the slot does not hold `weight_tensor->scale`. The vendor's entries are
around `0.0012` for a model whose weights peak at `0.19`, and `0x1004`, which
works, is `0.00049`. It wants a small positive fp16, and this driver's weight
scale for that model is four thousand times larger. That the output mirrors
about the zero point, 128..255 becoming 0..128, is consistent with a magnitude
far outside the usable window.

So the +0.998 match between the captured table and the scale implied by A is
about **the vendor's own quantisation**, where the weight scale really is small.
It does not license writing mesa's `weight_tensor->scale` into the same slot,
and round 46 assumed it did.

**The result worth keeping is depthwise.** `dwconv` with the table alone goes
from 6 distinct values to **28**, and its maximum from 128 to 245 against a
reference with 101 distinct. That is the first substantial movement depthwise
has shown from any change, and it moves toward the reference rather than
collapsing. Depthwise is per-channel quantised, so the table there is 32
different values rather than one repeated, which is presumably why it does
something for depthwise and harms the per-tensor shapes.

## 2026-08-10 round 46 (The real fp16 table regressed the working shapes, and I changed two things at once again)

Baselines 128/128 at both ends, so the result is real.

| | |
|---|---|
| conv2d-cal with the scale table | **0/128**, distinct 256 |
| cal_k3, cal_k1 | 0/128 |
| dwconv | 0/16 |
| mn_pw24 | 297/1024, unchanged |

distinct 256 means it ran and produced a full range of wrong values rather than
collapsing, so the pipeline is alive and the arithmetic is wrong.

**The round cannot be attributed, because it moved two things**: it wrote the
fp16 table *and* moved `0x5024` past it. That is the exact mistake this file
keeps recording, and I made it again one round after writing it down. They are
two knobs now, `ROCKET_SCALE_TABLE` and `ROCKET_SCALE_PTR`, and round 47 runs
each alone and both together against the same baseline.

**The decode is not in doubt** and does not depend on this: the 64 bytes before
the vendor's `0x5024` target are 32 uint16 that read as fp16 and match the scale
implied by A at +0.998. What round 46 failed to establish is which half of that
mesa can adopt, and that is now a separable question.

## 2026-08-10 round 46 hung, and it was my bug not the hardware

The board stopped at step 2, the first use of `ROCKET_SCALE_TABLE`, with the
step header printed and nothing after. Not a hardware hang: the `goto
biases_done` I added for that path sits at line 846 while the label is at 739,
so it jumps **backwards** and re-executes everything in between, forever.

The two existing gotos, for `ROCKET_DW_REC48` and `ROCKET_DW_FLOATBIAS`, are at
637 and 649 and jump forward to the same label, which is why rounds 44 and 45
ran fine and this one did not.

Fixed by dropping the goto and using a flag to skip the constant word instead.
A comment now says why, because the label being earlier in the function is not
visible from the place the jump is written.

## 2026-08-10 THE SURFACE IS DECODED, and it explains the magic word

Following `0x5024` rather than guessing finished this. In both models it points
at `0x0E0E` followed by zeros, identical, so the second operand is not the
depthwise difference. But the **deltas** are:

| | `0x5020` to `0x5024` |
|---|---|
| vendor regular, oc=32 | 320 bytes = 256 of table + **64** |
| vendor depthwise, oc=32 | 448 bytes |
| mesa, `DIV_ROUND_UP(oc,8)*64` | **256** |

And the 64 bytes immediately before the `0x5024` target, in both models, are
**32 uint16, one per output channel**. Read as fp16 they are the per-channel
weight scale:

```
fp16 there            0.001202  0.001271  0.00105   0.001131  0.000842 ...
scale implied by A    0.001224  0.001262  0.001046  0.001132  0.000843 ...
corr +0.998192, ratio 0.9332 to 1.0397   (fp16 rounding)
vs max|w_c|/127: only +0.875              (the approximation that misled me)
```

**So the surface is:**

```
0x5020 -> [A/B/C table]   64 B per 8 channels regular, 48 B per 8 channels depthwise
          [oc x fp16]     the per-channel weight scale
0x5024 -> 0x0E0E, then zeros
```

**This explains the magic word, and retires it.** mesa's `0x5024` is
`bias_addr + groups*64`, which lands **on** the fp16 scale table instead of past
it, so rounds 32 to 37 were sweeping values into channel 0's scale slot. `0x1004`
is fp16 `0.00049`, a small positive scale, and the rule `(w & 0x3f) == 0x04` with
a magnitude floor was describing **valid fp16 encodings** the whole time. The
"bitfield" was a float format seen through the wrong lens.

It also explains why exactly one word mattered: `conv2d-cal` is per-tensor
quantised, so every entry of that table is the same value, and getting the first
one right is getting all of them right.

`ROCKET_SCALE_TABLE` writes `oc` fp16 scales there and moves `0x5024` past them.
Round 46 built, not flashed.

## 2026-08-10 A and C are consistent with ONE per-channel scale, and mesa's formulas are the right shape

Round 45 reported that the captured A and C do not match mesa's formulas. That
reading was wrong, and the error was mine: I computed the per-channel scale as
`max|w_c| / 127`, and the toolkit does not use that.

Solving for the scale implied by the capture instead of assuming it:

| | |
|---|---|
| implied `s_c` from A, as a fraction of `max|w_c|/127` | **0.5933 to 0.9988**, median 0.846, varying per channel |
| take that implied scale and predict C | corr **+0.9982** |
| take the scale implied by C and predict A | corr **+1.0000** |

**A and C are mutually consistent under a single per-channel scale.** The
0.59-to-0.99 spread is the toolkit's clipping-optimised quantiser, which is why
a `max/127` approximation produced a per-channel varying ratio and looked like a
mismatch. That is the same trap as the fp16 table months ago: an approximate
reference makes a correct formula look wrong.

So `C = 0x4000 * s_c / max(s_c)` is **exactly** mesa's existing formula, and A's
shape, a multiple of the quantised weight sum, is mesa's too. For a tflite model
mesa knows `s_c` exactly from `weight_tensor->scales`, so it can reproduce both.

**What that does not explain**: round 45 wrote those formulas in 48-byte
records and the output still collapsed to two distinct values. So with the
values now understood, what remains for depthwise is the surface layout rather
than the arithmetic. The region has content this work has not accounted for,
including whatever `0x5024` points at, which for depthwise is `bo01+0x400` while
the table itself starts at `bo01+0x240`.

Everything needed to settle that is on disk: `dirty/vendorcap-dw-2026-08-10/`
and `sv_pairs.py dw`.

## 2026-08-10 round 45 (The 48-byte record alone is not the fix either, and the captured A and C do not match mesa's formulas)

Baselines 128/128 at both ends and no leak: conv2d-cal and cal_k3 both stay at
128/128 with the knob set.

| | 64-byte record | 48-byte record |
|---|---|---|
| dwconv | 0/16, distinct 6 | 0/16, distinct **2** |
| mn_dw1 | 3/32, distinct 124 | 2/32, distinct **2** |
| mn_conv0dw1 | 8/32 | **0/32** |

The output collapses to two values again, the same way the float bias did. So
the record size is not sufficient on its own, and the decision rule's second
branch applies: compare the values themselves against the capture.

**Both terms disagree with what mesa computes**, checked against `sv_dwu`'s known
weights and bias:

| | |
|---|---|
| captured A vs the **quantised** per-channel weight sum | corr **+0.9891**, so it is built from that |
| but `A / swq` per channel | ranges **127.0 to 215.8**, median 151.5, **not a constant** |
| best linear fit `A = 170.55*swq - 0.03*bias_q` | residual up to 18376 on a range of +-93649 |
| the bias term | contributes essentially nothing, coefficient -0.03 |
| captured C vs mesa's `0x4000 * wt_sc/max` | corr **+0.8752**, close but **not equal** |

So A is derived from the quantised weight sum with a per-channel factor this
work has not identified, and C is near mesa's relative-scale formula without
matching it. That is two unknowns on top of the record size, which is why
changing only the record size collapsed the output.

**Next, and it needs no board**: the capture and the exact inputs are both in
hand, so A and C can be solved rather than guessed. `dirty/vendorcap-dw-2026-08-10/`
holds the dumps and `sv_pairs.py dw` regenerates the ground truth.

## 2026-08-10 THE DEPTHWISE RECORD IS 48 BYTES, NOT 64 (and this corrects two earlier results of mine)

Round 44 concluded depthwise takes a float32 bias. **That was wrong**, and what
corrected it was reading the registers out of the capture instead of searching
the buffer for something recognisable.

`bo00` is not the regcmd; it is inside `bo01`. Decoding it gives the addresses
the vendor actually programmed, against the BO bases in `meta.txt`:

| | `sv_rgu` regular | `sv_dwu` depthwise |
|---|---|---|
| `0x1110` weights | offset 0 | offset 0, and the depthwise weight buffer is 576 = `0x240` bytes |
| `0x5020` bias base | offset **`0x2400`** | offset **`0x240`**, immediately after the weights |
| `0x5024` second operand | offset `0x2540` | offset `0x400` |
| `0x501c` mode | `0x0710` | `0x0510` |

So the surface the DPU reads for depthwise starts at `bo01+0x240`. **The float32
bias at `0x3198` is not it** and is librknnrt's own copy, which is why writing
it changed nothing useful.

**Decoding `0x240`:**

| record | A vs the known per-channel weight sum | C |
|---|---|---|
| **48 bytes**: A 8x int32 at +0, C 8x int16 at +32, **no B** | **+0.9696** | **peaks at exactly `0x4000`**, 32 distinct |
| 64 bytes, what mesa writes | -0.15 | maximum is not `0x4000` |

A regular conv is A at +0, B at +32, C at +48 in 64 bytes. **A depthwise layer
drops B and packs the record into 48.** mesa writing 64 means every channel's A
and C are read from the wrong offset, which is exactly why a depthwise layer
fires and saturates rather than producing nothing.

**This corrects the two entries above that said the vendor emits no
per-channel coefficient table for depthwise.** Both scans, the C-peak one and
the ground-truth A-versus-weight-sum one, tried 64, 32 and 128 byte blocks and
**never 48**. Two independent oracles agreeing meant only that they shared an
assumption, not that the answer was right. The positive control could not catch
it either, because the control is a regular conv and 64 is correct there.

`ROCKET_DW_REC48` writes A and C in 48-byte records for depthwise. Round 45
built, not flashed, with the knob checked against a regular conv.

## 2026-08-10 round 44 (The float bias alone does NOT fix depthwise, and the number that looks like an improvement is not one.)

Baselines 128/128 at both ends, and the knob does not leak: conv2d-cal and
cal_k3 are both 128/128 with `ROCKET_DW_FLOATBIAS` set.

| | int32 A/B/C table | float32 bias |
|---|---|---|
| dwconv | 0/16, distinct 6 | **0/16**, distinct 4 |
| mn_dw1 | 3/32, distinct 124, 19/32 constant | **5/32**, distinct **2**, **32/32 constant**, 26 at zp |
| mn_conv0dw1 | 1/32 | 8/32, distinct 2, 32/32 constant |

**The 3/32 to 5/32 is not an improvement.** The distinct count collapses from
124 to **2** and every one of the 32 channels becomes constant. The extra
"matching" channels are the ones where the CPU is also zero under ReLU, which is
exactly the metric caveat that a passing model, `mn_pw2`, exposed in round 43.
Read properly, the float bias made the output *worse*: it went from wrong and
varying to very nearly constant.

**What this does not overturn**: the capture itself. The bias really is a
contiguous 32-entry float32 block at `bo01+0x3198`, byte for byte, and there
really is no A/B/C table in the depthwise buffer. Dumping the region confirms a
clean block from `0x3198` to `0x3218` and nothing float-shaped immediately
after.

**So the format is necessary but not sufficient.** Something else in that buffer
is also read for depthwise. The surrounding bytes are not a second 32-entry
array: they look like records with float fields near `0.00417` at a 32-byte
spacing, but that spacing does not hold across 32 entries, so the structure is
not yet decoded and guessing at it again would repeat the mistake this round
already made.

**Next, and it is offline**: the dumps are kept at
`dirty/vendorcap-dw-2026-08-10/`, so the depthwise coefficient buffer can be
decoded properly against the known weights and bias before anything else is
flashed.

## 2026-08-10 THE DEPTHWISE FORMAT (A depthwise layer takes a float32 bias, not the int32 A/B/C table. Captured from the vendor runtime, with the control passing.)

The pair is `sv_rgu` and `sv_dwu`, ic = oc = 32 at 112x112, k=3, s=1, one
calibration set, only `groups` differing, biases known here exactly. Decoded
with the same oracle as the offline work, control first:

| | regular `sv_rgu` | depthwise `sv_dwu` |
|---|---|---|
| int32 A/B/C at `bo01+0x2400`, blocked 64/8/4 | **+0.9972** vs the per-channel weight sum | **+0.0000**, absent |
| float32 bias array | **not present anywhere in the buffer** | **byte for byte at `bo01+0x3198`** |

The control reproduces the host result exactly, `+0.9972` in the same blocked
layout, so the capture is real and the decode is trustworthy. The depthwise
match is not a correlation, it is the 128 bytes of the known bias array
byte for byte.

**The two formats are mutually exclusive, and the register that selects between
them is one this driver already sets correctly.** `0x501c` is `0x0710` for a
regular conv and `0x0510` for depthwise, which `rkt_regcmd.c` emits and which
matched the vendor in the offline register audit.

**So mesa has been telling the DPU to read that surface in depthwise mode and
then filling it with the regular integer table.** That is precisely what round
43 measured from the other side: `dwconv` fires and collapses to 6 distinct
values against a 101-value reference, which is a meaningless requant rather than
a missing one.

It also closes the loop on the offline dead end. The depthwise `.rknn` has no
A/B/C table because a depthwise layer does not use one, and the only per-channel
thing in the file was the raw float32 bias, which is exactly what the runtime
hands the hardware.

`ROCKET_DW_FLOATBIAS` writes `bias[oc] * in_sc * wt_sc[oc]` as float32 at the
start of the buffer for depthwise layers. Round 44 built, not flashed, with the
knob checked against a regular conv so a leak would show. Raw dumps kept in
`dirty/vendorcap-dw-2026-08-10/`.

## 2026-08-10 a wasted flash, and what it cost

The first depthwise capture round never ran. `S98npucap` hardcodes
`/opt/npu-cap/run-coefs.sh`, and the new script was injected as
`run-capture.sh`, which is the name the older per-axis round used. The board
booted, ran the previous round's 5x5-then-3x3 coefficient capture, and produced
a log with nothing to do with depthwise.

My error, and the check that would have caught it is one line: read what the
init script actually invokes before injecting, rather than matching the name in
a document that described a different round. `run-dwcoef.sh` now carries that
warning at the top, and the round is rebuilt under the right name.

Verified in the image before rebuilding this time, so the next flash is not
spent on the same class of mistake: the boot script's target file is the
depthwise round and calls the decoder, both models are present, `runner`,
`capture.so`, `librknnrt.so` and `python3.11` all exist.

## 2026-08-10 depthwise, the per-channel-scaled gap closed, and the capture prepared

The full-file sweep used correlation, which is scale invariant, so it finds
anything **proportional** to the bias. With per-channel weight quantisation
`A_i = bias_i / (in_s * wt_sc_i)` is not proportional to `bias_i`, so that sweep
could have missed it. Re-run with the per-channel-scaled references added,
`bias/wt_sc_c`, `sw/wt_sc_c`, `1/wt_sc_c` and `wt_sc_c`:

```
sv_dwu:  off 0x06018  float32 stride 4 +0  vs bias  corr +1.0000    (the raw float bias again)
         nothing else above 0.98
```

Still only the unquantised source bias. **The conclusion holds and is now tested
against the assumption that would have broken it.**

**The capture is prepared rather than left as a note.** `run-dwcoef.sh` captures
the vendor runtime's buffers for `sv_rgu` and `sv_dwu`, the single-variable pair
whose weights and biases are known here exactly, and `dwcoef_decode.py` applies
the same oracle to the captured bytes: every per-channel column, flat and
blocked layouts, against the bias, the weight sum and the per-channel-scaled
forms. **`sv_rgu` runs first as the positive control** and must reproduce its
`+0.9972` weight-sum hit before anything the depthwise capture says is readable.
Both models are staged in `dirty/npu-cap/`.

Needs `rock4d-spi-uboot-vendor.img` in SPI, and `rock4d-spi-uboot.img` back
before rocket will run again.

## 2026-08-09 offline depthwise, full-file sweep (There is no quantised per-channel coefficient anywhere in the vendor's depthwise model. The offline route is exhausted; this needs a runtime capture.)

Not just the length-prefixed blobs this time, the **whole file**, byte by byte:
int32, int16 and float32, strides 2, 4, 6, 8, 10, 16 and 64, every base offset,
correlated against the known bias, the known per-channel weight sum, and five
linear combinations of the two, since `A = bias - (in_zp - 0x80) * sw` and it is
not obvious which term dominates for a one-tap-per-channel kernel.

**Four hits above 0.98, and all four are the same thing:**

```
off 0x06018  float32 stride 4 +0  vs bias  corr +1.0000
off 0x06016  float32 stride 4 +2  vs bias  corr +1.0000   (the same array)
```

Verified exactly rather than by correlation: the 128 bytes at `0x06018` are the
known bias array byte for byte. And it appears in **exactly one of the four
builds**:

```
sv_dwu  (depthwise, compress_weight=False)  exact bias array at 0x06018
sv_rgu  (regular,   compress_weight=False)  NOT FOUND
sv_dw   (depthwise, compressed)             NOT FOUND
sv_rg   (regular,   compressed)             NOT FOUND
```

**That is the unquantised source bias, which the hardware cannot consume**, kept
by the toolkit when weight compression is off. It is bookkeeping, not a
coefficient table. Nothing else in the entire file is per-channel.

**So the vendor's depthwise `.rknn` contains no quantised per-channel
coefficient at all**, which is consistent with everything before it: no A/B/C
table under two structural oracles, and nothing in the 576-byte weight buffer
under three readings.

**The conclusion is that librknnrt builds the depthwise per-channel coefficients
at load time**, from the float bias and the scales, into a buffer the model file
never contains. Which means the offline route that answered the regular-conv
questions cannot answer this one.

**Next, and it needs the board**: capture the coefficient BO for a depthwise
layer from the vendor runtime, the way the 8192-byte regular-conv buffer was
captured. That needs `rock4d-spi-uboot-vendor.img` in SPI, and
`rock4d-spi-uboot.img` back afterwards for rocket.

## 2026-08-09 offline depthwise, weight buffer (Where the per-channel data goes is still open. Three readings of the 576-byte buffer fail, and weight compression is not the explanation.)

The 576-byte depthwise buffer is `oc*k*k*2`, two bytes per tap for int8 weights,
so it was the natural place for the missing per-channel data. Three readings,
each with a control:

| reading | result |
|---|---|
| int8 under a fitted scale, sweeping `\|w\|max/k` for k in 60..260 | **64.6%** best overlap |
| the same on the REGULAR model's 9216-byte buffer, as a positive control | **92.1%**, so the method does find weights |
| fp16, 288 halves | 31 nan/inf, values to 53216, not weights |
| per-channel 18-byte blocks, channel c's 9 weights in block c | **14.2%**, against a **mispaired control of 13.9%** |

The last line is the important one: pairing block `c` with channel `c` is no
better than pairing it with channel `c+7`, so that test carries no signal at all.

**Weight compression is not the explanation.** `posprobe_planes.py` has always
passed `compress_weight=False` and `sv_pairs.py` did not, which was a plausible
reason for a buffer not to decode. Rebuilding the pair with it off gives
**identical** numbers, 92.1% and 64.6%.

**And the main result now holds across both build settings:**

```
sv_rg   63 vectors   C peaks at 0x4000:  0x9080 len 256
sv_rgu  44 vectors   C peaks at 0x4000:  0x9080 len 256     (compress_weight=False)
sv_dw   33 vectors   C peaks at 0x4000:  NONE
sv_dwu  51 vectors   C peaks at 0x4000:  NONE                (compress_weight=False)
```

The table is found in both regular builds, at the same offset and size, and in
neither depthwise build.

One scare along the way, recorded so it is not mistaken for a finding: the
A-column oracle appeared to fail on `sv_rgu`, which would have voided the run.
It was a scripting bug, the depthwise weight sum passed as the reference for
both models. The C-peak oracle above is unaffected and fires correctly.

**Still open**: where a depthwise layer's per-channel bias and requant actually
live. Not the A/B/C table, and not the 576-byte weight buffer in any reading
tried so far.

## 2026-08-09 offline depthwise, second oracle (A per-channel coefficient table is absent from the vendor's depthwise model under two independent tests, one of which has a working positive control.)

The first oracle (C peaking at `0x4000`) only covered one grouping, so here is a
second one built on ground truth. `sv_dw` and `sv_rg` were generated here, so
their weights and biases are known exactly.

**Calibrating it first**, on the known-good table in `sv_rg` at `0x9080`:

```
A column vs the known per-channel WEIGHT SUM : corr +0.9972
A column vs the known BIAS                   : corr -0.3608
```

So the probe is the weight sum, not the bias, which is what
`A[oc] = bias - (in_zp - 0x80) * sw` predicts when the weights are random: the
`sw` term dominates. A first attempt correlated against the bias and found
nothing anywhere, including in the model where the table is known to exist. A
second attempt used a flat stride and also found nothing, for the same reason:
the layout is **blocked**, channel `i` at `(i//8)*64 + (i%8)*4`, which no
constant stride reaches. Both were oracle bugs, caught by the positive control.

**With the blocked scan over every vector, every block size, group, element
size and base offset:**

```
sv_rg:  0x009080 len 256  block 64 group 8 elem 4 base +0   corr +0.9972
sv_dw:  NONE
```

Exactly one hit in the regular model, at mesa's own layout, and nothing anywhere
in the depthwise one. **Two independent structural oracles now agree that the
vendor emits no per-channel coefficient table for a depthwise layer**, and mesa
writes one regardless. That is round 43's `dwconv` signature from the other
side: the MAC fires and the requant it is handed is meaningless, so the output
collapses to 6 distinct values against a 101-value reference.

**Where the per-channel bias goes instead is still open.** The 576-byte
depthwise weight buffer is the natural suspect, since 576 is `oc*k*k*2`, two
bytes per tap for int8 weights. Correlating it against the known weights gives
nothing, but that is expected because correlation is order-sensitive and the
depthwise tap order is permuted. An order-insensitive multiset check gives 28.5%
overlap, which looks like a miss but **cannot conclude anything**: rknn picks
its own quantisation scale, measured earlier at about 7% below `max/127`, so a
different scale changes the multiset even if the weights are present. That test
needs the toolkit's actual scale before it means anything.

## 2026-08-09 offline depthwise coefficients (The vendor emits no A/B/C table for a depthwise layer, and mesa writes one anyway. That is the requant signature round 43 measured.)

Using the single-variable pair from `sv_pairs.py dw`, ic = oc = 32 at 112x112,
k=3, s=1, one calibration set, only `groups` moving.

Decoding the coefficient table with the layout this project established, 64
bytes per 8 channels, A int32 at +0, B int16 at +32, C int16 at +48:

| | A | B | C |
|---|---|---|---|
| **sv_rg**, regular | `-152272, -102671, 91137, ...`, range +-200k | small ints | `14098, 12727, 14416, ...`, **max exactly 16384** |
| **sv_dw**, depthwise | `0, 0, 0, 0, 0, 1`, range -1.2e9 to 3.9e8 | `-5888, 0, 1, 0, 4` | `0, 0, 0, ...` with two large negatives |

The regular one decodes exactly as mesa models it. `C` peaks at `0x4000`, which
is what `C[oc] = round(2^14 * wt_sc[oc] / max wt_sc)` requires of the max-scale
channel. The depthwise one is not a coefficient table in that layout at all.

**That could just mean the wrong blob was picked**, so it was checked properly:
scanning **every** vector in both files for one whose C column peaks at exactly
`0x4000`, which is a layout-specific signature rather than a plausibility
judgement:

```
sv_rg:  0x009080 len 256:  C peaks at 0x4000 (1 of 32 channels at the max)
sv_dw:  NO vector anywhere has a C column peaking at 0x4000
```

Exactly one hit in the regular model, at the expected size of 8 bytes per
channel, and none in the depthwise one.

Scoped honestly: this rules out the 8-channels-per-64-bytes grouping. A
depthwise table with a different grouping would not be detected by that oracle.

**So mesa hands the hardware a regular-conv A/B/C table for a depthwise layer
and the vendor does not.** That is what round 43 measured from the other side:
`dwconv` fires and collapses to 6 distinct values over a 101-value reference,
which is what a meaningless requant looks like, not a weight DMA fault.

**Next**: find what the vendor does write for depthwise, which is now a
well-posed offline question over the same pair, and only then touch the board.

## 2026-08-09 round 43 (What the failures actually look like. Depthwise fires and saturates; the chain writes one constant. And the metric has a caveat that a passing model exposed.)

Both baselines 128/128 with 0 constant channels.

| model | distinct | constant channels | reading |
|---|---|---|---|
| conv2d-cal, works | 128 | 0 of 128 | |
| **dwconv** | **6**, cpu 101, min 0 max 128, zp 99 | 0 of 16 | **fires, then saturates to the rails** |
| **conv2x**, chain | **1**, every pixel 127, zp **132** | 16 of 16 | one constant that is **not** the zero point |
| mn_conv0 | 60, all within 126..185 | 10 of 32, none at zp | narrow band around 128 |
| mn_dw1 | 124 | 19 of 32, 8 at zp | mixed, per channel |
| mn_conv0dw1 | 22 | 22 of 32, 9 at zp | |
| mn_pw24 | 256 | 358 of 1024, 354 at zp | |
| **mn_pw2, works** | 256 | **8 of 64, all at zp** | |

**The last row is a caveat on the metric itself.** `mn_pw2` is correct on
every channel and still has 8 channels pinned at the output zero point, because
with ReLU and `out_zp = 0` a channel whose output is everywhere non-positive is
legitimately constant. So "pinned at the zero point" is **not** evidence of a
dead channel in these models, and the round 43 decision rule's first branch has
to be read with that in mind. It was written before this was known.

**What does read cleanly:**

`dwconv` is not an empty convolution. It produces 6 distinct values spanning 0
to 128 against a reference with 101, so the MAC fires and the result collapses
onto the rails. That is a requant signature, not a weight DMA one, which is the
opposite of what the decision rule expected to find.

`conv2x` writes a single value, 127, across the whole surface, and 127 is not
its zero point of 132. A chain whose output is one non-zero-point constant is a
different failure again from either of those.

**Checked and cleared since**: `calculate_weight_sum`'s depthwise branch indexes
`weights[0][x][y][oc]`, which is right for a `[1][kh][kw][channels]` tensor, so
the A term's weight sum is not the cause.

**No image was built for this.** The signature narrows depthwise to the requant
path, but there is no specific enough hypothesis yet to be worth a flash, and
the next step is to work out which of A, B, C and the OUT_CVT shift is wrong for
depthwise, offline, the way the register question was settled.

## 2026-08-09 offline depthwise pair (Round 42's hypothesis is dead, killed without the board. And the registers are not the depthwise bug either.)

Round 42 was built on `g_dw1` against `g_k3s1`, which differ in channels and
spatial size as well as in being depthwise. 41 registers differed and nothing
said which of them were about depthwise. Compiling a proper pair with
`sv_pairs.py dw`, ic = oc = 32, 112x112, k=3, s=1, one calibration set, moving
only `groups`, leaves **15**:

```
0x100c 0x101c 0x1024 0x1030 0x3018 0x400c 0x4030 0x4038 0x4044
0x4050 0x40b0 0x40b4 0x40b8 0x501c 0x5044
```

**`0x1018` and `0x1040` are not in that list.** They differed on geometry
alone, so `ROCKET_DW_SPLITVALS` tests nothing and **round 42 should not be
flashed**. The single-variable discipline paid for itself again.

And every one of the 15 that is a mode bit already matches mesa:

| register | mesa | vendor depthwise / regular |
|---|---|---|
| `0x100c` | `dw ? 1 : 0` | `0x1` / `0x0` |
| `0x101c` | `dw ? oc*k*k*2 : ic*oc*k*k` | `0x240` / `0x2400` |
| `0x1024` | `dw ? 1 : oc-1` | `0x02020001` / `0x0202001f` |
| `0x1030` | `wbpk = dw ? k*k*ic/8 : ic*k*k*2` | `0x24` / `0x240` |
| `0x3018` `0x400c` `0x4030` `0x4038` `0x4044` `0x4050` `0x501c` `0x5044` | all `dw ?` branches | all match |
| `0x40b0` `0x40b4` `0x40b8` | OUT_CVT | must differ, the pair has different weights |

**So the registers are not the depthwise bug, exactly as the coefficient region
turned out not to be.** Two hypotheses closed offline in one sitting, one of
them a round that was already built.

**Round 43** asks what the depthwise output actually looks like instead.
`perch.py` now also reports the distinct count and how many channels are pinned
at the output zero point, which separates "the MAC never fired" from "the MAC
fired on the wrong operands". Those need completely different next steps and a
maxdiff cannot tell them apart. Built, not flashed.

## 2026-08-09 round 41 (The region is closed. It is not copies of the word, filling it is harmless, and it is not the cause of anything that remains.)

Both baselines 128/128.

| `ROCKET_FS_FILL` on mn_pw24 | 1 | 2 | 8 | 32 | 128 | 512 | 1024 | whole region |
|---|---|---|---|---|---|---|---|---|
| channels | 297 | 297 | 297 | 297 | 297 | 297 | 297 | **297** |

Every count identical, so **the region is not repeated copies of the word** and
the constant cannot be pushed further there. The old float surface still gets
408, and that difference is real but is not something a uniform word can
reproduce. The decision rule's third branch applies: say so and stop pushing it.

Filling the whole region is harmless, which is worth knowing on its own:
conv2d-cal 128/128, cal_k3 128/128, mn_pw2 64/64. And `dwconv` and `conv2x` are
unmoved by any of it, as in round 40.

**So this region is characterised, fixed, and is not the cause of what remains.**

**The next target is depthwise, and the first concrete lead came for free on the
host.** Comparing a vendor `.rknn` compiled depthwise against one compiled as a
regular conv, 41 registers differ and most are geometry. Two are not:

| register | vendor depthwise | vendor regular |
|---|---|---|
| `0x1018` | `0x40000505` | `0x40000404` |
| `0x1040` | `0x14000000` | `0x10000000` |

and those are exactly the values `rkt_regcmd.c` selects on `split`. **A depthwise
layer that is not split gets the regular values from mesa and the split values
from the vendor.** `ROCKET_DW_SPLITVALS` makes depthwise take them, and round 42
tests it, with the knob checked against a regular conv so a leak would show.
Built, not flashed.

## 2026-08-09 round 40 (Depthwise and chaining do not depend on this word at all, so they have separate causes. And at 1024 channels the constant is WORSE than the surface it replaced.)

Both baselines 128/128.

| model | all six known-good words | the old float surface |
|---|---|---|
| dwconv | 0/16 every time | **0/16** |
| conv2x | 0/16 every time | **0/16** |
| **mn_pw24**, oc = 1024 | **297/1024, identical for all six** | **408/1024** |

**Depthwise and chaining are settled with respect to this word.** Six different
words that all compute correctly elsewhere, plus the old float surface, and
nothing moves either model by a single channel. They have their own causes, and
those can now be attacked without the weight-bit coincidence in the way.

**The constant is not a strict improvement.** The decision rule named this
case before the run, and it happened: at 1024 output channels the old per-weight
float surface gets 408 channels right and the constant gets 297. Whatever is
consumed there scales with something `mn_pw24` has more of, and the floats
satisfy the requirement for more channels by accident than one word does on
purpose. One word is enough at oc=128 and at oc=16, both measured directly, so
the count is not simply one per output channel either.

**Round 41** adds `ROCKET_FS_FILL=<n>`, which writes the word into the first n
slots, 0 meaning the whole region, and sweeps n on `mn_pw24` against both
numbers. It also checks that filling does not harm the layers that already work,
because writing past what a layer needs may itself be harmful. Built, not
flashed.

## 2026-08-09 round 39 (Two more models come good, and for the first time some fail PARTIALLY, which is new information.)

Both baselines 128/128.

| model | what it is | channels |
|---|---|---|
| **mn_pw2** | real pointwise, ic 32 to oc 64 | **64/64** |
| **md003** | | **16/16** |
| mn_pw24 | pointwise, oc = 1024 | **297/1024** |
| mn_dw1 | depthwise | 3/32 |
| dwconv | depthwise | 0/16 |
| mn_conv0 | first conv, the 4 channel path | 0/32 |
| conv2x | two ops in one graph | 0/16 |
| mn_conv0dw1 | two ops | 1/32 |
| MobileNet v1 | whole model | FAIL, top1 0 against 754 |
| md011 | | **no output line at all** |

**Partial per-channel results are new.** Everything on this driver used to be
all or nothing, so 297 of 1024 and 3 of 32 are signal. So is the fact that
`mn_pw2` now works: pointwise from the real model, not a synthetic probe.

`md011` printed its header and nothing after it, so something in that run
died silently. Not attributed to the NPU until it is reproduced.

**Round 40 applies the method that just worked to what still fails.** `0x1004`
was fitted on conv2d-cal at oc=128, and there is no reason it is the right word
for a depthwise layer, a 4 channel first conv, or oc=1024. So sweep the
known-good words on `dwconv`, `conv2x` and `mn_pw24`, each against the old float
surface for contrast. If some word moves `dwconv` off 0 of 16, depthwise was the
same bug needing a different word, and the requirement is not a constant but
something the driver has to compute. If nothing moves it, depthwise has a
separate cause and the coefficient word is settled for it. Built, not flashed.

## 2026-08-09 round 38 (Every regular convolution shape computes, with the constant as the default and no knobs set. 1x1 included, which was the last non-depthwise shape on the open list.)

| model | shape | channels |
|---|---|---|
| conv2d-cal | 5x5 stride 2 | **128/128** |
| **cal_k3** | **3x3** | **128/128** |
| **cal_k1** | **1x1** | **128/128** |
| cal_s1 | 5x5 stride 1 | **128/128** |
| cal_oc16 | 16 output channels | **16/16** |
| cal_izp0 | input zero point 0 | **128/128** |
| conv2d-cal, whole model | | 2/2 OK, relu maxdiff 1 |
| cal_k3, whole model | | 2/2 OK, relu maxdiff 1 |
| cal_k3 with the **old float surface** | | **0/128** |
| control, conv2d-cal again | | 128/128 |

**The 1x1 wall and the kernel size wall were the same bug.** Both were recorded
for months as separate hardware mysteries, with their own theories: the
pointwise one had "the DPU runs and writes the whole surface with exactly
out_offset while ignoring the weights, the input, and the A operand". Neither
was about geometry. A dequantised weight was landing in a bitfield, and a model
computed or not according to whether its first weight carried the right bits.

**Round 39** goes at what is left from before all this: depthwise, chained
operations, and MobileNet, which has both. Those were also attributed to
separate causes, so the question is whether they were the same coincidence.
Built, not flashed.

## 2026-08-09 round 37 (THE 3x3 KERNEL COMPUTES. The kernel size was never the dividing line, it was one weight-derived word landing in a bitfield.)

Both baselines 128/128.

| step | model | word | channels |
|---|---|---|---|
| 2 | conv2d-cal | `0x1004`, smallest the rule allows, never run before | **128/128** |
| 3 | conv2d-cal | `0x3fc4`, every free bit set | **128/128** |
| 4 | conv2d-cal | `0x1005`, near miss | 0/128 |
| 5 | conv2d-cal | `0x0fc4`, near miss | **128/128** predicted to fail |
| 7 | cal_s1 | `0x1004` | **128/128** |
| 9 | cal_oc16, oc=16 | `0x1004` | **16/16** |
| **10** | **cal_k3** | baseline, mesa's own word | **0/128** |
| **11** | **cal_k3** | **`0x1004`** | **128/128, every channel** |

**The 3x3 kernel computes on every output channel.** One constant, `0x1004`,
makes conv2d-cal, cal_s1, cal_oc16 and cal_k3 all correct.

**So the kernel size was never the dividing line.** `rkt_coefs.c` filled that
word with a dequantised weight, which meant whether a model computed came down
to whether its FIRST WEIGHT happened to carry the right bits. conv2d-cal's did,
cal_k3's did not. Every round that tried to explain 5x5 against 3x3, on this
project going back months, was chasing that coincidence. It also explains the
offline result that the vendor's coefficient buffer carries no kernel size
dependence: there was never any to find.

**The rule from round 36 was partly wrong and is refitted.** `0x0fc4` has bits
12 and 13 clear and was predicted to fail; it passes. Against all 24 words:

```
(w & 0x3f) == 0x04    and    ((w >> 6) & 0xff) >= T,   0x21 < T <= 0x3f
```

every failure has `(w>>6)&0xff` at most `0x21` and every pass at least `0x3f`,
so the exact threshold sits in a gap nothing has probed yet. Bits 14, 15 and
everything above are free.

**mesa now writes `0x1004` there by default**, and nothing else in the region.
The buffer size is deliberately unchanged this round so that content is the only
variable. Round 38 runs the default against everything that has never worked:
`cal_k1`, depthwise, the chain, and the whole-model numbers. Built, not flashed.

## 2026-08-09 round 36 (The word decoded. One rule fits all twenty data points: the low six bits are 000100 and at least one of bits 12 and 13 is set.)

Baselines and the upper-half-zeroed control all 128/128.

| word (low 16) | bits 15..0 | channels |
|---|---|---|
| `0x1a44` | `0001101001000100` | **128/128** |
| `0x1a04` | `0001101000000100` | **128/128** |
| `0x1a84` | `0001101010000100` | **128/128** |
| `0x1044` | `0001000001000100` | **128/128** |
| `0x2044` | `0010000001000100` | **128/128** |
| `0xff44` | `1111111101000100` | **128/128** |
| `0x0044` `0x0144` `0x0244` `0x0444` `0x0844` `0x4044` `0x8044` | bits 12 and 13 both clear | 0/128 |
| `0x1a45` `0x1a06` `0x1a0c` `0x1a14` `0x1a40` `0x1a00` `0x1aff` | low six bits not `000100` | 0/128 |

```
(w & 0x3f) == 0x04    and    (w & 0x3000) != 0
```

fits every pass and every failure. Bits 6, 7, 8, 9, 10, 11, 14, 15 and
everything above bit 15 are free.

**This is a bitfield, and `rkt_coefs.c` is filling it with a dequantised float
weight.** The driver works today because that particular weight happens to carry
`000100` in its low six bits and a set bit at 12 or 13, which is luck.

**Round 37 tests it as a prediction rather than refitting it.** `0x1004` is the
smallest word the rule allows and has never been run, `0x3fc4` sets every free
bit at once, and `0x1005` and `0x0fc4` are the near misses beside them that must
fail. Then the same constant on `cal_s1`, `cal_oc16` and `cal_k3`, to see
whether it is a constant or a function of the geometry.

Fixed in the same build: the knobs wrote at a hardcoded `0x400`, which equals
`groups*64` only because every model probed so far has oc=128. On `cal_oc16` it
is `0x80`, so they would have been writing into the A/B/C table. They now use
`groups*64`, which is what makes the other models testable at all.

Built, not flashed.

## 2026-08-09 round 35 (It is a bitfield in the low 16 bits. bit0 clear, bit2 set, high byte nonzero, and bits 16 to 31 don't care.)

Both baselines and the round trip clean.

| word | low 16 as `hh ll` | channels |
|---|---|---|
| `0xc2db1a44` exact | `00011010 01000100` | **128/128** |
| `0xffffff44` | `11111111 01000100` | **128/128** |
| `0xc2801a44` bits 16..22 cleared | `00011010 01000100` | **128/128** |
| `0x005b1a44` sign and exponent cleared | `00011010 01000100` | **128/128** |
| `0xc2db1a04` | `00011010 00000100` | **128/128** |
| `0x00000044` | `00000000 01000100` | 0/128 |
| `0xc2db0044` | `00000000 01000100` | 0/128 |
| `0xc2db1a45` | `00011010 01000101` | 0/128 |
| `0xc2db1a40` | `00011010 01000000` | 0/128 |
| `0xc2db1aff` | `00011010 11111111` | 0/128 |

**Every pass has bit 0 clear, bit 2 set and a nonzero high byte. Every failure
breaks exactly one of those three.** And three separate words with the top half
mangled all pass, so **bits 16 to 31 are don't care entirely.**

So the four bytes that `rkt_coefs.c` fills with a dequantised float weight are
consumed as a bitfield in their low 16 bits. It works today because the weight
mesa happens to write has the right two bits, which is luck, not design.

**Round 36** finishes the map: each single bit of 8..15 on its own with bit 2
set, and bits 1 and 3..7 varied with a known good high byte, plus `bit0 set` as
the probe that must fail. The smallest passing word is what mesa should write,
and then the 197888 byte surface can go. Built, not flashed.

## 2026-08-09 round 34 (The round trip holds, so the knob is sound. And the word is not being read as a float: sign and exponent are don't care, the low byte is not.)

mesa's actual word, dumped rather than computed:

```
WORD 0xc2db1a44   as float -109.55130004882812
first 16 bytes: 44 1a db c2  7a 80 9c 41  b6 c0 6a c3  29 67 7a c0
```

That also settles round 33: the string `-109.55` parses to a different low
mantissa than the exact product does, so every value in that sweep missed the
low bits.

| probe | word | channels |
|---|---|---|
| exact, the round trip | `0xc2db1a44` | **128/128** |
| **sign flipped** | `0x42db1a44` | **128/128** |
| **exponent + 1, so twice the value** | `0xc35b1a44` | **128/128** |
| mantissa cleared | `0xc2800000` | 0/128 |
| **low byte cleared** | `0xc2db1a00` | **0/128** |
| zero | `0x00000000` | 0/128 |
| baselines either side | | 128/128 |

**Negating the number and doubling it change nothing, and clearing the low byte,
worth 0.0005 as a float, destroys all 128 channels.** Nothing reads a float that
way. The sign and exponent behave as don't care and the low bits behave as a
field, which means the four bytes mesa fills with a dequantised weight are being
consumed as something else entirely, and that it works at all is luck.

**Round 35** takes the word apart: the low byte alone, the low byte under all
ones, each upper field cleared in turn, and the low byte moved while everything
above it is held. If `0x00000044` alone computes, this whole 197888 byte surface
is one byte. Built, not flashed.

## 2026-08-09 round 33 (WITHDRAWN. The sweep swept the wrong values, and its own internal check is what caught it.)

| step | channels |
|---|---|
| 1) baseline | 128/128 |
| **2) `KEEP=4`, mesa's own word untouched** | **128/128** |
| **`FS_F0=0xc2db199a`, `KEEP=4`** | **0/128** |
| `FS_F0` = 0, -109.55, +109.55, -1.0, +1.0, -1e6, -1e-6, `0x43d3a666` | all 0/128 |
| 12) baseline | 128/128 |

`0xc2db199a` is supposed to be the word mesa itself writes. `ROCKET_FS_F0`
writes four bytes exactly where `ROCKET_FS_KEEP=4` preserves four bytes, so if
the value matched, those two runs would be byte identical. They are not.

The pair `-109.55` and `0xc2db199a` agreed with each other, which was the
control for the parser, so the knob reads its argument correctly. **What is
wrong is my host computation of `fs[0]`**, which means every value in that
sweep was a wrong value and the sweep says nothing about sign or magnitude.
Do not cite round 33 for anything except this.

What still stands is round 32, which never depended on knowing the value: four
bytes kept is enough, zero bytes is not.

**Round 34 reads the word off the board instead of computing it** and derives
its probes from what it dumped, so it cannot repeat this. Step 4 is a round
trip, writing back exactly the dumped word, which must reproduce the baseline;
if it does not, the knob is broken and every `FS_F0` result is void. The probes
after it are that same word with the sign flipped, the exponent raised by one,
the mantissa cleared, and the low byte cleared, which separate "specific value"
from "magnitude class" from "bit pattern". Built, not flashed.

## 2026-08-09 round 32 (It is ONE float32. The whole 197888 byte float surface comes down to the first four bytes.)

Both baselines 128/128.

| `ROCKET_FS_KEEP` | channels matching |
|---|---|
| 256, 128, 64, 32, 16, 8, **4** | **128/128, all of them** |
| **0** | **0/128** |

**Keeping four bytes is enough.** Everything else in the region can be zero and
conv2d-cal is still byte correct on every output channel.

And it is not simply "must be nonzero": round 30 put `0x43d343d3` there, about
423.3, and every channel died. The word mesa happens to write is

```
fs[0] = wt_sc * (w[0][0][0][0] - wt_zp) = -109.55 = 0xc2db199a
```

So one scalar decides the whole layer, and it has to be the right one. The two
known points differ in sign as well as magnitude, `0xc2` against `0x43` in the
high byte.

**Round 33** sweeps exactly that word with `ROCKET_FS_F0`, everything else
zeroed, taking a float or a raw hex pattern since it is not established that the
hardware reads it as a float at all: 0, -109.55, +109.55, -1.0, +1.0, -1e6,
-1e-6, and the two known words by hex. If every negative passes it is the sign,
mesa is right by luck, and the fix is a single constant instead of a 200 KB
surface. `-109.55` and `0xc2db199a` are the same word and must agree, which is
the parser's own control. Built, not flashed.

## 2026-08-09 round 31 (Measured at last: the load bearing slice is at most 256 bytes, against the 197888 mesa writes and the 1936 rounds 26 and 27 believed in.)

Both baselines 128/128, so the sweep counts.

| `ROCKET_FS_KEEP` | channels matching |
|---|---|
| 1936, 1600, 1024, 512, **256** | **128/128, all of them** |
| **0** | **0/128** |

Round 30 showed zeroing those same first 256 bytes fails, so the two bracket it
from both sides. **Everything from `0x500` to `0x0b90` is irrelevant, and the
load bearing part is at most the first 256 bytes**, which is 64 float32.

Computed on the host, those 64 floats are output channel 0's first 64 taps, 4
spatial positions across 16 input channels, running from -344.30 to 328.65 with
one exact zero. Nothing about that looks like a table of scales.

**This is the second big size result and it is a measurement, not a reading.**
`rkt_coefs.c` sizes this region as `MAX2(ic*oc*k*k, 8192)` floats, 197888 bytes
for conv2d-cal, and at most 256 of them are doing anything.

**Round 32** bisects inside the 256: 256, 128, 64, 32, 16, 8, 4, 0, with the
baseline at both ends. 4 would be a single scalar, which would also explain why
every substitution failed, since a scalar has to be the right number. 64 would
be `ic` floats, one spatial position across the input channels. Built, not
flashed.

## 2026-08-09 round 30 (Not a per-channel table. Changing those 256 bytes destroys all 128 output channels, not the 64 a per-channel layout would touch.)

Both baselines clean, so the run counts.

| step | channels matching CPU |
|---|---|
| 1) untouched float surface | **128/128** |
| 2) the 256 bytes zeroed | **0/128**, maxdiff 128 on every channel |
| 3) the 256 bytes as fp16 per-channel scales | **0/128** |
| 4) baseline again | **128/128** |

The first branch of the decision rule. A 4-byte-per-channel table would have
left channels 64..127 alone; instead every channel is pinned at the output zero
point. And substituting a plausible large float fails exactly like substituting
zero, so it is not a magnitude problem either: `0x43d3 0x43d3` read as float32
is 423.65, the same order as the dequantised weights that work.

**Three rounds have now tried to substitute a meaning into this region and all
three failed identically.** The vendor's per-channel fp16 reading is solid about
the vendor's own files and does not describe how mesa drives the same address.

**So measure the size instead of guessing the meaning.** The extent has never
actually been measured: `0x0b90` was picked because that is where the vendor's
constant tail starts, which says nothing about this driver. All that is known is
that keeping `0x400..0x0b90` works and zeroing all of it fails, so the boundary
is somewhere in those 1936 bytes. `ROCKET_FS_KEEP=<n>` keeps the first n bytes
and zeroes the rest, and round 31 sweeps 1936, 1600, 1024, 512, 256, 0 with the
baseline at both ends. Landing on 512 would mean one float per output channel,
and that the fp16 attempt failed on element size alone; landing on 1600 would
mean `ic*k*k`, exactly one output channel's worth of weights. Built, not
flashed.

## 2026-08-09 offline register audit (The register hypothesis from round 29 is dead. mesa's configuration matches the vendor at this geometry, DPU_RDMA included.)

Round 29 concluded the format of the surface at `groups*64` must come from a
register, since mesa and the vendor put different things at the same address and
both compute. That is checkable without a board, because mesa's regcmd is mostly
literals and simple expressions and the vendor's stream is in the `.rknn`
(`reg_audit.py`, decoding with `extract_regcmd.py`).

Against `g_cal`, compiled at conv2d-cal's exact geometry:

| | mesa | vendor |
|---|---|---|
| `0x501c` BRDMA cfg | `0x0710` | `0x0710` |
| `0x5034` | `0x41` | `0x41` |
| `0x5044` | `0x40000010` | `0x40000010` |
| `0x500c` `ow-1` | `0x27` | `0x27` |
| `0x5014` `oc-1` | `0x7f` | `0x7f` |
| `0x101c` `ic*oc*k*k` | `0xc800` | `0xc800` |
| `0x1020` | `0x190` | `0x190` |
| `0x1080` padding | `0x01010202` | `0x01010202` |
| `0x4030` | `0x007f0710` | `0x007f0710` |
| `0x4050` | `0x80011111` | `0x80011111` |
| `0x4100..0x4154` | all zero | all zero |

The last two are this project's own fixes, and they land on the vendor's values.
**So the configuration is not where the two differ**, and the round 29
explanation has to be withdrawn as a hypothesis rather than carried forward.

The audit's raw "38 different" line is an artifact and must not be quoted: for
many registers mesa has a literal in the first-conv path and a computed
expression in the general one, and the script reports the first literal it
finds. `0x500c` shows this exactly, literal `0x6f` from the first-conv ladder
against the general path's `ow-1 = 0x27`, which is the vendor's value.

**What has never been asked is granularity.** 256 bytes over 128 output channels
is 2 bytes each, over 64 channels 4 bytes each. Round 30 reports per output
channel (`perch.py`) instead of one number for the model, so the damage pattern
names the element size. If only channels 0..63 break, mesa's float32 surface is
a per-channel table of 128 floats, 512 bytes rather than 200 KB, and the fp16
attempt failed for being the wrong element size rather than the wrong idea.
Built, not flashed.

## 2026-08-09 round 29 (Those 256 bytes must hold mesa's own floats. Nothing else works there, including the vendor's own kind of content. So mesa and the vendor are reading that region under different formats, and the difference is a register.)

Round 28 could not decide because it moved two things at once. This moved one.

| step | result |
|---|---|
| 1) the float surface that computes | **2/2 OK** |
| **2) that same surface, only the 256 table bytes overwritten with fp16 scales** | **0/2 FAIL**, raw 127 |
| **3) that same surface, only those 256 bytes zeroed** | **0/2 FAIL**, raw 120 |
| 4) 2 again on `cal_k3` | 0/2 FAIL |
| 5) repeat of 1 | **2/2 OK**, nothing drifted |

The dump shows the isolation was real: 256 nonzero at the table **and 1656
nonzero in `0x500..0x0b90`**, so the float surface behind it was present and
untouched. Those 256 bytes were the only difference from a passing run.

**So `0x400..0x400+2*oc` must contain exactly mesa's float32 dequantised
weights.** Zeroing them fails and replacing them with a correct per-channel
fp16 weight scale fails the same way.

**That is not a contradiction of the offline work, it is the interesting part.**
The vendor's own model files put one fp16 per output channel at that address and
unreproducible filler after it, and the vendor computes. mesa puts float32
across `0x400..0x0b90`, every byte of it load bearing, and mesa computes. Two
different formats in the same place, both working. A buffer cannot be read two
ways by itself, so **the format and length of that surface must come from a
register**, and that is where mesa and the vendor diverge, not in the bytes.

So the pre-written rule's "go decode `0x500..0x0b90` offline" does not apply:
offline already showed that region is filler in the vendor's files. **The next
comparison is the DPU_RDMA register block, mesa's emitted stream against a
vendor `.rknn` compiled at the same geometry**, which `extract_regcmd.py`
already reads and which needs no board. For `sv_k5` the vendor sets `0x5004=0e`,
`0x501c=0x710`, `0x5034=0x41`, `0x5044=0x40000010`, and `0x5020/0x5024=0`,
though base addresses in a `.rknn` are relocation placeholders and mean nothing
until mesa's values sit next to them.

## 2026-08-09 round 28 on the board (The region is read, the offline reading of it is not overturned, and the round could not test it because I moved two things at once.)

| step | result |
|---|---|
| 1) the old float surface, `conv2d-cal` | **2/2 OK** |
| 2) fp16 per-channel weight scale | 0/2 FAIL, relu maxdiff 128 |
| 3) the same table, `cal_k3` | 0/2 FAIL |
| **4) control, the table zeroed** | **0/2 FAIL, as it must** |
| 5) the scale relative to the largest channel | 0/2 FAIL, relu maxdiff 119 |
| 6) the table plus the vendor's constant tail | 0/2 FAIL |
| 8) repeat of 1 | **2/2 OK**, nothing drifted |

The dump confirms the knob fired: 256 nonzero bytes at `0x400..0x500`, nothing
after, `table[0:8]` all `0x43d3`.

**The value was not the problem.** `conv2d-cal`'s weight scale really is
`3.9125464` (it is a synthetic calibration model, output scale 32.0), and fp16
of that really is `0x43d3`. mesa wrote what it was asked to write.

**The round could not decide anything, and that is my error.** It changed two
things at once: it put the table at `0x400` **and** left everything after it
zero. Round 27 zeroed both as well. So nothing so far separates

- `0x400..0x400+2*oc` must hold mesa's floats, from
- `0x500..0x0b90` is the load bearing part and the table is fine.

That also withdraws the neat "this explains round 27" line in the round 28
offline entry below: a properly nonzero fp16 table fails too, so "the floats
there were nonzero when read as fp16" is not sufficient as an explanation.

**What survives, and is not weakened by any of this:** the region IS read, since
zeroing it fails. And the offline results stand on their own, because they are
about the vendor's own files, not about this driver: the table is 2 bytes per
output channel, it is per-channel, it scales exactly with that channel's weight
scale, and nothing in the vendor's coefficient buffer depends on kernel size.

**Round 29** splits the two: `ROCKET_FS_TABLE_OVER` writes the float surface
exactly as the passing configuration does and then overwrites only the table's
bytes, and `ROCKET_FS_HOLE` is its complement, the same surface with only those
bytes zeroed. Built, not flashed.

## 2026-08-09 round 27 (The k-dependence is localised to 1936 bytes, and it is load bearing. From 200 KB down to that.)

Knob confirmed: `0x400..0x0b90` zeroed, `0x1600` reads `00 3c`, nothing past
`0x2000`.

| step | result |
|---|---|
| `conv2d-cal` untouched | 2/2 OK |
| `conv2d-cal` + vendor tail (round 26) | 2/2 OK |
| **`conv2d-cal` + tail + `0x400..0x0b90` zeroed** | **0/2 FAIL** |
| `cal_k3` + tail + the same slice zeroed | 0/2 FAIL |
| constant input, both, tail + midzero | **byte identical**, distinct 91, `127 177 255 112 ...` |

So that slice is load bearing, and the last line is the point: **once the whole
coefficient buffer is made k-independent, the two kernel sizes behave
identically.** In round 26, with only the tail grafted, the buffer still differed
between them in exactly this slice, and they behaved differently. **The
k-dependence is in `0x400..0x0b90`, 1936 bytes.**

That is the search space down from 204800 bytes to 1936, and the two captured
vendor buffers are on disk to compare against.

**What the slice looks like**, per 64-byte block, in the two captures:

| region | k=5 nonzero | k=3 nonzero | bytes differing |
|---|---|---|---|
| `0x400..0x700` | full, 64 of 64 | full, 64 of 64 | most |
| `0x700..0x0b00` | **sparse, 0 to 37** | **dense, 55 to 64** | nearly all |
| `0x0b00..0x0b80` | 45 to 54 | 45 to 54 | **none** |

So the constant region really begins around `0x0b00`, and in the middle the 5x5
capture is sparse where the 3x3 one is dense, which is the opposite of what a
per-weight table would do.

**1682 of the 1936 bytes differ between the two captures, and those two models
also differ in their weights**, because `gen_geom.py` gives each geometry its own
random tensor. So nothing here separates "varies with the kernel" from "varies
with the weights", and guessing at the format from two confounded samples is how
today's retracted claims happened.

**The next capture has to be designed rather than repeated**: models that differ
in exactly one thing. Same weights with a cropped kernel, the way `mutate_k.py`
already does for tflite, so the shared taps are identical; and same kernel with
different output channel counts. That is offline work on the model generator
before any board time.

## 2026-08-09 round 26 (mesa's 200 KB float surface is NOT NEEDED: a 5232-byte model-independent constant does the same job. And that refutes round 24's reading.)

Knob confirmed fired: `0x1600` reads `00 3c 00 3c ...`, `0x2000` onward is zero,
**nonzero past 0x2000: 0 of 197888**.

| step | result |
|---|---|
| `conv2d-cal` untouched | 2/2 OK, relu maxdiff 1 |
| **`conv2d-cal` with the vendor tail grafted** | **2/2 OK, relu maxdiff 1** |
| `conv2d-cal` with the region zeroed | 0/2 FAIL |
| `cal_k3` with the tail | 0/2 FAIL, unchanged |
| `cal_k1` with the tail | 0/2 FAIL, unchanged |

**The model that computes is exactly as correct with 197888 bytes of its
coefficient buffer deleted and replaced by a 5232-byte constant captured from the
vendor.** So the per-weight float32 surface `rkt_coefs.c` builds is not needed:
the buffer goes from 206080 bytes to 8192, and the region that
`FINDINGS-FLOATSURFACE.md` called a value-dependent blob is a model-independent
constant. That is a simplification worth having regardless of the open bug, and
it removes the largest unexplained payload in the driver.

**And it refutes what round 24 concluded.** That round read "a k-independent
table makes both kernel sizes agree" as locating the k-dependence in this region.
With the tail grafted, both models now receive **byte-identical content from
0x0b90 onward**, conv2d-cal is correct and cal_k3 is still flat at the zero
point. **Identical bytes, different behaviour, so the k-dependence is not
there.** Round 24 agreed at a wrong value, which was never evidence.

What remains k-dependent in that buffer is the slice `0x400..0x0b90`, which still
holds the first 1936 bytes of mesa's float surface. Round 27 zeroes exactly that
slice, keeping A/B/C and the tail, with conv2d-cal as the control: if it survives,
the coefficient buffer is k-independent apart from A/B/C, and if cal_k3 still
fails then the whole buffer is exonerated.

## 2026-08-09 full vendor coefficient dump (The buffer is ~8 KB with a model-independent tail, against mesa's 206 KB of per-weight floats. Structure below, blobs saved.)

`hexlen` raised to 8192 so the whole dumped region prints. Two models, same
geometry apart from the kernel, 128 output channels:

| region | content | model dependent |
|---|---|---|
| `0x000..0x400` | the A/B/C table | yes |
| `0x400..0x500` | 128 uint16, one per output channel | yes |
| `0x500..0x0b90` | weight related | yes |
| **`0x0b90..~0x0e46`** | **a 13-byte pattern `ff ff 00 fc ff 03 f0 ff 0f c0 ff 3f 00` repeated 54 times** | **no** |
| `~0x0e46..0x1200` | more constant content | no |
| `0x1200..0x1600` | zeros | no |
| **`0x1600..0x2000`** | **1280 uint16, every one `0x3c00`, which is fp16 1.0** | **no** |

**The two buffers are byte identical from `0x0b90` to the end of the dump**,
across different weights and different kernel sizes. That is 5232 bytes of
constant, ending in a table of fp16 ones.

Saved so this does not have to be re-captured:

```
vendor-capture/vendor-coefbuf-k5.bin        8192 bytes, the 5x5 capture
vendor-capture/vendor-coefbuf-k3.bin        8192 bytes, the 3x3 capture
vendor-capture/vendor-coef-tail-0x0b90.bin  5232 bytes, the constant tail
```

**What this says about mesa.** `rkt_coefs.c` writes, at `groups*64`, a float32
array with one entry per weight, sized `MAX2(ic*oc*k*k, 8192)` floats, which for
conv2d-cal is 204800 bytes. The vendor's whole buffer is around 8 KB and most of
it is a constant that does not depend on the model at all. The float framing is
not a detail that is unfilled, it is the wrong shape for the region.

**Not claimed**: that writing the vendor's tail fixes anything. conv2d-cal
computes today *with* mesa's float surface, and zeroing that surface breaks it,
so mesa's floats are doing something real for that model. The next experiment is
to keep mesa's A/B/C and overlay the constant tail, with conv2d-cal as the
control that must survive; `ROCKET_BIAS_FILE` already exists and loads a whole
buffer from a file, so the mechanism is there.

## 2026-08-09 round 25 (The sweep found nothing, and it exposes two errors of mine in round 24. Read this before acting on that entry.)

Twelve values from `0x0010` to `0x4000`, plus `0x2000`, all on `conv2d-cal` with
the controls passing 2/2 at both ends. Every one of them: relu maxdiff 119 to
128, top1 npu = 1. **No constant in that region restores the model that works.**

**Error 1, an over-reading.** Round 24 said that giving both kernel sizes a
k-independent table "makes them agree", and treated that as progress. They agree
because they are **equally wrong**, not because either is right. Agreement at a
wrong value is not evidence that the vendor's format is the fix, and this sweep
shows that format with any constant makes `conv2d-cal` worse rather than better.

What survives from round 24 is only this, and it is solid because the control
could fail and did: **zeroing the region takes `conv2d-cal` from 2/2 to 0/2, so
the region is load bearing.** mesa's float surface is evidently right for
`conv2d-cal`, since that model computes with it.

**Error 2, and the worse one: I under-dumped and read the gap as zeros.**

```
dump #1: bias len=8192  nonzero (whole buffer) = 4608
   hexdump covered 2048 bytes, of which 1684 nonzero
   never looked at: 2924 nonzero bytes beyond 0x800
```

The capture reported 4608 nonzero bytes in 8192 and printed only the first 2048.
I described the layout as "128 uint16, then `0e 0e`, then zeros" when **more than
half the nonzero content was in the part that was never printed**. That claim is
withdrawn: what is established is the first 1024 bytes are the A/B/C table and
the 256 bytes after it are 128 uint16, one per output channel. Everything I said
about the rest was an artifact of the dump length.

Fixed in the capture patch, `hexlen` 2048 to 8192, so the whole dumped region is
printed. Capture image rebuilt and verified to carry the rebuilt kernel.

## 2026-08-09 round 24 (PARTLY WITHDRAWN by round 25 above: the region is load bearing, but "the k-dependence is found" was an over-reading. The coefficient tail is load bearing, and replacing mesa's float surface with the vendor's shape makes 5x5 and 3x3 agree.)

Controls first. The knob fired, coefficient buffer md5 `1beebc1f` to `84278999`,
distinct 209 to 140. And the control could fail, and did:

| conv2d-cal, which computes 2/2 today | result |
|---|---|
| untouched | 2/2 OK, relu maxdiff 1 |
| **region ZEROED** (`ROCKET_FS_ZERO=1`) | **0/2 FAIL, relu maxdiff 128** |
| region written the vendor way, one u16 per channel | 0/2 FAIL, relu maxdiff 119 |

**So the region is load bearing.** Zeroing it breaks the only model that works.

**And the payload.** On a constant input, with the vendor-shaped table in place:

| | first 12 channels |
|---|---|
| `conv2d-cal` (k=5) | `128 177 255 128 128 128 128 196 188 255 128 128` |
| **`cal_k3` (k=3)** | **byte identical** |

Before this, on the same test, k=5 returned the correct `requant(bias)` and k=3
returned a flat zero point. **Giving both a table that does not depend on the
kernel makes them agree.**

**That is the k-dependence.** `rkt_coefs.c` writes a float32 surface at
`groups*64` whose size is `MAX2(ic*oc*k*k, 8192)` floats and whose content is one
entry per weight, so both its length and its values move with the kernel, and it
is load bearing. The vendor writes a per-output-channel uint16 table there, which
does not depend on the kernel at all.

It also explains why every single variable before this was refuted with a clean
control: the regcmd, the weight layout, the bias, the requant and A, B and C are
all correct, and this was the only k-dependent payload left. It was mistaken for
padding added to stop an out-of-bounds read.

**The value is not known.** `0x1700` was the middle of the captured range and
it over-scales, both models saturating to 255. The captured values ran 5400 to
6400 across 128 channels of models whose per-channel weight scales differ; for a
per-tensor model like conv2d-cal the correct table should be uniform, so a single
constant can be right. Round 25 sweeps for it with conv2d-cal as the oracle: the
value that returns it to 2/2, against its known scales, gives the formula.

## 2026-08-09 VENDOR COEFFICIENT CAPTURE (the region mesa zeroes is not zero on the vendor: a 128-entry per-output-channel uint16 table.)

First attempt did not run: `rknn_init = -1` both models, because the vendor NPU
driver never probed. With mainline U-Boot and TF-A in SPI the Rockchip SCMI
power domain and reset protocols are absent, `SCMI protocol 17 not active` and
`22 not active`, so enabling the NPU clock returns -71. **The vendor kernel needs
`rock4d-spi-uboot-vendor.img` in SPI.** After that swap both models loaded and
both BO dumps came out, the four-dumps-per-boot patch working as intended.

**The coefficient buffer, 8192 bytes dumped, same structure in both:**

| offset | content |
|---|---|
| `0x000..0x400` | the A/B/C table, ~870 of 1024 bytes nonzero, matching mesa's `groups*64` layout for 128 output channels |
| **`0x400..0x500`** | **`a0 16 61 17 65 17 4b 17 ...`, 256 bytes = 128 uint16, one per output channel** |
| `0x500` onward | `0e 0e` then zeros |

| dump | values | distinct | correlation with the per-channel weight scale |
|---|---|---|---|
| k=5 | 5691..6394 | 113 | **+0.873** |
| k=3 | 5436..6202 | 116 | **+0.856** |

So the region immediately after the A/B/C table holds a **per-output-channel
16-bit multiplier that tracks the weight scale**.

**CORRECTION, within an hour of writing the above.** I first said mesa "writes
zeros there". It does not. `rkt_coefs.c` fills that region by default with a
**float32 dequantised weight surface**, thousands of entries, sized
`MAX2(ic*oc*k*k, 8192)` floats, and only zeroes it under `ROCKET_FS_ZERO`. So the
difference is sharper than "empty against full":

| at `groups*64` | |
|---|---|
| mesa, default | float32 array, one entry per weight, thousands of them |
| **vendor** | **128 uint16, one per output channel, then `0e 0e`, then zeros** |

Same address, different element type, different length, different meaning. The
TODO comment in that function is about the float content being unfilled, and the
capture says the whole float framing is wrong.

**A confound I built in**: `gen_geom.py` gives each geometry its own random
weights, so the k=5 and k=3 tables differ for that reason too. Nothing here
attributes the difference between them to the kernel. The one thing this does
establish is that **the vendor populates a region mesa leaves empty**, which is
a real and unimplemented piece of the datapath.

Whether it explains the kernel-size split is a separate question and is not
claimed here. It is a candidate for the *gain* being wrong, which is what was
measured: against the CPU the k=3 response is about 80x too small and the k=1
response about 3.5x too large, while the spatial mapping is correct. The models
that fail are per-tensor quantized, so the correct table for them would be
uniform rather than varying, and mesa writes zero rather than uniform.

## 2026-08-09 (Offline is exhausted for the last question, and here is why. A vendor coefficient capture is built and waiting.)

**The coefficient buffer cannot be read out of a `.rknn`.** Scanning a compiled
model end to end finds only metadata, an index ramp followed by `1.0f` floats,
and the weight blob. The A/B/C table and the float surface are built by
librknnrt at load time, which is why the earlier float-surface work was done
from runtime captures rather than from the file. So "what does the vendor put in
the coefficient buffer for a 3x3 conv" has no offline answer.

That matters because it is the only surface left. For one model with only the
kernel cropped, everything the driver produces is verified: the regcmd in
absolute terms against a vendor build at the same geometry, the weight layout
including the 32-channel grouping, the weight contents (read by the CMAC,
confirmed by forcing them), the bias tensor, the requant, and A, B and C. The
coefficient buffer's size was equalised in round 23 with no effect, and its
contents are the part that could not be checked.

**Built and ready to flash** (`dirty/sdcard-cap.img`), the vendor capture stack
rather than another rocket experiment:

- the vendor kernel's capture patch was a one-shot, `cap_bo_done`, so only the
  first model of a boot got dumped. Now `cap_bo_n < 4`, numbered in the header,
  so one boot captures both models.
- the `bias` BO dump goes from 1024 bytes to 8192, showing 2048, so it covers
  the whole A/B/C table for 128 output channels and the start of the float
  surface.
- two models at the same 16 in, 128 out, 80x80, stride 2, differing only in the
  kernel: `g_cal_rk3576.rknn` at 5x5 and `g_cal_k3_rk3576.rknn` at 3x3.

**What it decides, stated before the run:** if the two coefficient buffers are
byte identical, exactly as mesa's own are, the coefficient buffer is excluded on
the vendor side too and whatever depends on the kernel sits below everything
either driver writes. If they differ, the difference is the answer and can be
carried straight into mesa.

This costs two flashes, to the capture image and back, and it is a different
image from the rocket rounds. Recorded because the last several rounds were
flashed without a decision rule agreed first, twice with probes that could not
have measured anything (rounds 18 and 19), which is a bad way to spend someone
else's hardware time.

## 2026-08-09 round 23 (The float surface size is inert. Refuted by a control that could fail, and it was the last k-dependent thing in any buffer.)

The knob fired: `cal_k3`'s coefficient buffer went from 75008 to 206080 bytes,
md5 `8aeb5d4b`.

| step | result |
|---|---|
| constant input, all three with `ROCKET_FS_ELEMS=51200` | **byte identical to without it**, still 12 / 1 / 45 distinct |
| real inputs, k=3 and k=1 with the count equalised | fail identically |
| **control: `conv2d-cal` with the count forced small, 8192** | **2/2 OK, unchanged** |

The control is what settles it. Shrinking the region from 206080 to 34048 bytes
on the model that computes correctly changes nothing at all, so the hardware is
not sensitive to that size in either direction. **The float surface size is not
the k dependence**, and the oversizing mesa added to stop an out of bounds read
is not doing what its comment claims either.

That was the last k-dependent thing in any buffer. So, for one model with only
the kernel cropped:

| surface | state at k=3 |
|---|---|
| regcmd | verified against a vendor build at the same geometry, in absolute terms |
| weight layout | verified, plane order, lane order and the 32-channel grouping |
| weight contents | read by the CMAC, confirmed by forcing them |
| bias tensor | shared with the model that computes |
| requant | identical, `shift=25 scale=0x7d34` in every log line |
| A, B, C | A is the bias since `(in_zp - 0x80)` is zero, B refuted, C is `0x4000` |
| coefficient buffer size | equalised, no effect |
| spatial mapping | correct, an input impulse lands in the right output pixels |

**Everything the driver produces is verified, and a constant input at the input
zero point still returns three different answers depending on the kernel size**,
for a computation whose every MAC product is zero by construction. The k
dependence is below everything the driver writes.

## 2026-08-08 round 22 (Found the last k-dependent thing: the coefficient buffer carries a FLOAT SURFACE region whose size mesa derives from the weight count.)

| model | biases buffer | weights buffer | first 12 bytes |
|---|---|---|---|
| k=5 | 206080 | 204800 | `ca ff ff ff 95 0c 00 00 7b 27 00 00` |
| k=3 | 75008 | 73728 | **identical** |
| k=1 | 34048 | 2048 | **identical** |

The A values match across all three, as a shared bias tensor requires. The sizes
do not, and mesa's own expression reproduces every one of them exactly:

```c
bufsize = groups * 64 + MAX2(wt_elems, 8192) * sizeof(float) + 0x100;
wt_elems = ic * oc * k * k;
```

k=5 gives `1024 + 204800 + 256`, k=3 `1024 + 73728 + 256`, k=1
`1024 + 32768 + 256` with the 8192 floor doing the work. So that buffer is an
A/B/C table of `groups*64` bytes followed by a **float surface region sized from
the weight count, and therefore from the kernel**.

mesa's comment is explicit that this is a guess: the region exists because the
DPU RDMA was reading past the end of the BO and stalling, it is "bounded by the
full weight count" because "the float surface can hold no more floats than there
are weights", its content is left zeroed, and filling it properly is a TODO.
`FINDINGS-FLOATSURFACE.md` records the surface as load-bearing and
value-dependent.

**This is the only k-dependent thing left.** Everything else about these three
models is verified identical or verified correct against a vendor .rknn compiled
at the same geometry: the regcmd in absolute terms, the weight layout including
the 32-channel grouping, the bias tensor, the requant, and A, B and C.

Round 23 adds `ROCKET_FS_ELEMS` to override that element count, so the three
models can be given a byte-identical coefficient buffer with only the kernel
differing, and runs the constant input and a real input that way. The control
is `conv2d-cal` with the count forced small: it computes today, so shrinking a
region the hardware reads should change something, and if nothing moves anywhere
in the round the knob is inert and the answer is elsewhere.

## 2026-08-08 round 21 (B refuted with a working control. And the constant-input baselines say k=5 is exactly right, k=3 is clamped away, k=1 goes below the zero point.)

The control worked: `conv2d-cal` with `ROCKET_B_VALUE=0` on a real input went
from relu maxdiff 1 to 14 and failed. So the knob reaches the hardware and B does
matter. But the constant-input baselines came back **byte identical with B and
without it**, for all three kernel sizes, which is what should happen: with a
constant input the input sum that B multiplies is zero. **B is not the
k-dependent term.**

The baselines themselves are the result. Constant input at `in_zp`, so the MAC is
zero by construction and the answer must be `requant(bias)`:

| | first 12 channels |
|---|---|
| cpu, all three | `128 131 138 127 128 127 126 132 132 141 122 127` |
| **k=5** | `128 131 138 128 128 128 128 132 132 141 128 128` |
| **k=3** | `128` everywhere |
| **k=1** | `127 128 128 112 123 117 94 128 128 128 26 113`, min 0 |

**k=5 is exactly correct**: it matches the CPU wherever the CPU is at or above
128 and sits at 128 below, which is the hardware ReLU at `out_zp`. **k=3 is
clamped away entirely.** **k=1 goes below the zero point**, which the same ReLU
forbids at k=5, so even the clamping behaviour depends on the kernel.

And mesa's coefficients cannot explain it. `calculate_bias_correction` and
`calculate_weight_sum` are both multiplied by `(input_zero_point - 0x80)`, which
is zero at `in_zp` 128, so A is just the bias, and the three models share one
bias tensor because `mutate_k.py` crops only the weights. C is `0x4000` for a
per-tensor conv. B is refuted above.

So round 22 dumps the coefficient buffer for all three and compares it byte for
byte. Identical md5s would mean identical coefficients, identical requant and a
MAC of zero produce three different answers, putting the k-dependence below
everything the driver writes. Different md5s would mean mesa is emitting
different coefficients after all, and that difference is visible without any
hardware at all.

## 2026-08-08 round 20 (The probe finally works. The spatial mapping is CORRECT at every kernel size, so the tap pairing theory is dead. What is wrong is the gain, and the baselines say it more simply.)

An input impulse with the real kernel, so nothing has to cancel:

| model | CPU footprint | NPU footprint | magnitudes |
|---|---|---|---|
| k=5, control, impulse at (20,20) | rows 9..10, cols 9..10 | **same** | cpu 1510..1880, npu 747..1039 |
| k=5, impulse at (30,14) | rows 14..15, cols 6..7 | **same** | same ratio |
| **k=3** | rows 9..10, cols 9..10 | **same** | cpu 1510..1880, npu **19..28** |
| **k=1** | row 10, col 10 | **same** | cpu 1585, npu **5477** |

**Every kernel size puts the response in exactly the right place**, and moving
the impulse moves it correctly. So no tap is paired with the wrong input pixel,
and the idea that 144 products cancel because of a mis-pairing is refuted. The
fault is in the **gain**: against the CPU, k=3 is about 80x too small and k=1
about 3.5x too large.

**And the baselines are a much simpler failing case than the impulses.** The
baseline is a constant input at exactly `in_zp`, so `(in - 0x80)` is zero, the
MAC is zero by construction, and the answer must be `requant(bias)`. `cal_k3`
and `cal_k1` are conv2d-cal with only the kernel cropped, so all three carry the
same bias and the same requant, which every log line confirms as `shift=25
scale=0x7d34`. The answer is still different:

| k | baseline distinct values |
|---|---|
| 5 | 12 |
| **3** | **1, flat at the zero point** |
| 1 | 45 |

**Three different answers to a computation whose every input is identical.**
No input data, no spatial mapping, no meaningful weight contribution: just bias
through the requant, and it depends on the kernel size.

The only k-dependent term in that path is **B, the weight zero point
correction**. The MAC computes `sum((in - 0x80)(w - 0x80))` while the true
convolution wants `sum((in - in_zp)(w - wt_zp))`, and B carries the difference,
which is proportional to the input sum over the kernel window and therefore to
the tap count: 400 against 144 against 16.

Round 21 runs the constant input on all three kernel sizes with B as it is and
with `ROCKET_B_VALUE=0`. If the three baselines converge with B removed, B is
the term that does not belong. The control is `conv2d-cal` with B forced to 0
on a real input: it computes correctly today, so removing a correction it needs
must break it, and if it does not the knob never reached the hardware.

## 2026-08-08 round 19 (VOID again, and the rescale was not the real fault. The impulse KERNEL is badly conditioned and fails at k=5 too.)

| | NPU | CPU |
|---|---|---|
| k=5 impulse, the control | `distinct=1`, 128..128 | `distinct=128`, 128..255 |
| k=3 impulse | `distinct=1`, 128..128 | `distinct=128`, 128..255 |

The rescale worked, on the CPU side the models now span the full byte range, and
mesa recomputed the requant from the new scale, shift 25 to 22. The NPU still
returns exactly 128. **So the output scale was not why round 18 failed.**

The impulse kernel needs 399 taps sitting exactly at the weight zero point to
cancel against one live tap, and mesa stores weights as `w - 0x80` with the `B`
operand doing that correction, so the signal is a four hundredth of a large
cancellation. **It fails at k=5, the kernel size that computes correctly**, which
means it was never capable of measuring anything. The `VOID` guard added after
round 18 reported it plainly instead of letting the percentages be read.

**Put the impulse in the input instead.** The kernel stays the real, well
conditioned one from a model that computes; only the input changes. Feed the
input zero point everywhere, feed it again with one pixel raised, subtract. The
response is the kernel footprint, and where it lands names the mapping:

```
out[y][x] responds iff  stride*y + ky - pad_top == y0  for some tap ky
```

Nothing has to cancel, and `impulse_in.py` prints the CPU footprint alongside the
NPU one in the same run, so a step that shows nothing on both sides is a broken
probe rather than a hardware fact. Round 20 measures k=5 as the reference
footprint, then k=3 and k=1.

## 2026-08-08 round 18 (VOID, and its control is what caught it. Both impulse models returned a flat out_zp.)

Step 2 was the control: the k=5 impulse, whose kernel size computes correctly,
had to come back as an identity mapping. It did not. Every channel reported
"best match cpu ch16 at 71.6%".

Step 5 says why:

| model | NPU result |
|---|---|
| `cal_k5_imp` | `distinct=1 mean=128 min=128 max=128` md5 `66a83b6c3142` |
| `cal_k3_imp` | `distinct=1 mean=128 min=128 max=128` md5 **`66a83b6c3142`** |

Both return a flat zero-point surface, with the same md5. The "71.6% best match"
was a constant 128 agreeing with the reference wherever the reference sits below
the zero point, which favours whichever channel is most often low. **No mapping
could be read from either, so step 3 says nothing about tap pairing.**

**The fault is in my model, not the hardware.** One live tap out of 400 carries
about 1/400 of the dynamic range the full kernel had, and I left the output scale
at the original 32, so the product underflowed the requant to `out_zp`. The
probe could not have worked on any hardware.

Fixed two ways. `mutate_impulse.py` now sets the output scale from the largest
product a single tap can produce, 32 to 4.34 here, and on the CPU both models
span the full byte range with 200 or more distinct values per channel. And
`taps.py` refuses to report a mapping when the NPU surface is flat, so this trap
cannot be walked into silently again.

That is the **third** control-design failure today, after the nonzero-versus-
distinct count in round 8 and the cannot-fail control in round 12. The
difference here is that the control was built to fail and did, before anything
was concluded. The rule that keeps holding: **state what the control's failing
value looks like, and make sure the probe could produce a large effect at all.**

## 2026-08-08 round 17 (Both controls worked. For k=3 the DPU reads the coefficients AND the CMAC reads the weights. Every stage is alive and the answer is still zero.)

Read in the stated order, the controls first:

| | result |
|---|---|
| knob fired? | weights `distinct 224` -> `distinct 1`, first bytes `7f` |
| control that must fail: `conv2d-cal` + forced weights | md5 `80e64aab` -> `07852cc6`, relu maxdiff 1 -> 127, **wrecked** |

So the results count:

| `cal_k3` | md5 | mean | min..max |
|---|---|---|---|
| plain | `2cae07f3` | 128.32 | 128..131 |
| **A forced to 0x40000** | `f9a4969a` | **135.82** | **133..139** |
| **every weight forced to 0x7f** | `4a574bef` | 128.04 | 128..131 |

**The DPU reads the coefficient buffer for k=3**, which separates it from the
md003 family where forcing A at two values changed nothing at all. **And the
CMAC reads the weight buffer**, since forcing it changed the output md5.

So for a 3x3 conv: the regcmd is verified against the vendor in absolute terms,
the weight layout is verified including the 32-channel grouping, the weights are
read, the coefficients are read, and the result is still `out_zp` plus a couple
of counts.

**The weight probe was weak and I am not reading magnitude into it.** Forcing
every weight to one value makes a box filter, and a box filter on a smooth ramp
input produces a nearly constant output whether or not anything is wrong. The
md5 change establishes the buffer is read; the small change in mean establishes
nothing. That probe could not have shown a large effect even in a working
driver.

**An impulse kernel can.** `mutate_impulse.py` (new) gives output channel c a
single live tap at `(c/k, c%k)`, weight zero point everywhere else, live on input
channel 0 only. A correct convolution then makes channel c a copy of the input
shifted by that tap. If the hardware pairs a tap with the wrong input pixel, NPU
channel c matches the CPU's channel c' instead, and `taps.py` (new) recovers that
mapping. **A wrong pairing is exactly what makes 144 products cancel toward zero
while every buffer is read correctly**, which is the state we are in.

The control is the same probe at k=5, which computes correctly and therefore
must come back as an identity mapping. If it does not, `taps.py` is wrong and the
k=3 answer means nothing.

## 2026-08-08 (continued, host-side: mesa vs vendor at k=3 in ABSOLUTE terms, and the weight layout closed including the 32-channel grouping.)

**The absolute diff, which round 16 never actually did** (it compared deltas):

| reg | k=3, FAILS | k=5, WORKS |
|---|---|---|
| CNA 0x1080 | `01010000` vs `00000101` | `02020101` vs `01010202` |
| CNA 0x1084 | `00000000` vs `ffffff80` | same difference |
| DPU 0x40ac | `00000000` vs `fffffffc` | same difference |
| DPU 0x40b4 | `00000019` vs `0000001a` | same difference |

**The same four registers differ at k=3 as at k=5**, and all four are the two
model families' own conventions: padding, the pad value `in_zp - 0x80` (0 for the
tflite family, `-128` for the ONNX one), and the two requant fields. Since k=5
computes correctly with exactly these four differences, none of them can be why
k=3 does not. **The regcmd is cleared in absolute terms, not just in its delta.**

**And the weight layout is now closed, including the case `cal_k3` actually
exercises.** The oc=16 probes could not see the output-channel grouping, because
mesa packs `[oc/32][ic/32][kx][ky][oc%32][ic%32]` and 16 channels are a single
group. At OC=64, IC=16, K=3 the vendor stores:

| observed | |
|---|---|
| plane order | `0..8` then `0..8` again |
| run length | **512 bytes** = 32 oc x 16 ic |

which is exactly mesa's nesting: output channels in groups of 32, the spatial
planes inside each group, and within a plane oc-major with ic contiguous. Sizes
agree too: for oc=ic=16 at k=3 the vendor's buffer is 2304 contiguous bytes and
mesa writes 2304, matching the DMA count in 0x101c, with mesa's allocation being
four times larger and the excess simply unread.

So **for a 3x3 convolution every byte and every register the driver produces is
now verified against the vendor**, and the MAC still comes out zero.

`cal_k3` carries conv2d-cal's own bias tensor, since `mutate_k.py` crops only the
weights, so its `out_zp + 0..2` is what `requant(bias)` with a MAC of exactly
zero gives, not a MAC that nearly cancels. Round 17 asks the two remaining
questions directly: `ROCKET_ATEST` says whether the DPU reads the coefficient
buffer for k=3, which would separate it from the md003 family where A is ignored,
and `ROCKET_WTEST`, now available on the generic path, says whether the CMAC
reads the weights at all. The control that must fail is the same weight knob on
`conv2d-cal`, which computes correctly.

## 2026-08-08 (host-side, no board: the weight layout is FULLY verified against the vendor, for k=3 as well as k=5. It is correct.)

The plane probe was redesigned after the first attempt was recorded as unsafe.
Plane p now gets a value BAND, wide enough that per (oc, ic) variation inside it
cannot be mistaken for a neighbour, so the tensor is ordinary rather than rank
one; and a plane is identified by a run of exactly `oc*ic` bytes rather than by
sampling one byte.

**Validated on the kernel size that works before being trusted on the one that
does not:**

| k | runs of exactly 256 bytes | stride | plane order as stored | matches mesa |
|---|---|---|---|---|
| **5, known good** | 25 | 256 | `0..24` | **yes** |
| **3, fails** | 9 | 256 | `0..8` | **yes** |

The probe reproduces mesa's own `[kx][ky]` nesting on the 5x5 that computes
correctly, so its answer for 3x3 counts, and that answer is that the plane order
is right too.

**And the order within a plane**, from two more probes read structurally with no
assumption about the byte values:

| weights vary with | 256-byte block structure | conclusion |
|---|---|---|
| `ic` only | period 16: `80 91 a2 b3 ... 7f` then repeats | ic is contiguous |
| `oc` only | runs of 16: `80` x16, `91` x16, ... | oc changes every 16 bytes |

That is `[oc][ic]`, oc-major with ic contiguous, which is exactly what
`rkt_coefs.c` writes, and the same answer the pointwise probe gave.

**So the whole weight buffer is verified correct against the vendor for k=3:**
plane order, within-plane lane order, buffer size (73728 bytes =
`k*k*oc*ALIGN(ic,32)*2`), and the DMA count in 0x101c matching the bytes
actually written. Together with round 16, where mesa's register delta across the
kernel change is identical to the vendor's, **everything the driver produces for
a 3x3 conv is now verified, and the MAC still nearly cancels.**

Two probe-design faults on the way here, both caught before they became
findings: a filter that accepted 0 as an encoded value matched a block of zeros
in both lane probes, and predicting the exact quantized bytes failed because the
toolkit's weight quantization is not the symmetric max/127 rule assumed. Reading
the block *structure* rather than its values avoids both.

**What is left for the k=3 case**, now that the regcmd and the weights are
excluded: the bias and coefficient buffer contents, the address registers, which
cannot be diffed against a static .rknn because they are unpatched placeholders
there, and the input staging, which is shared with the 5x5 that works and drives
it from a byte-identical input BO.

## 2026-08-08 round 16 (Mesa's register response to the kernel is EXACTLY the vendor's. The regcmd is not where the k=3 failure lives.)

The same model one kernel apart, on both sides:

| reg | mesa 5x5 -> 3x3 | vendor 5x5 -> 3x3 |
|---|---|---|
| CNA 0x101c | `0000c800` -> `00004800` | identical |
| CNA 0x1020 | `00000190` -> `00000090` | identical |
| CNA 0x1024 | `0404007f` -> `0202007f` | identical |
| CNA 0x1030 | `03200027` -> `01200027` | identical |
| CNA 0x1080 | `02020101` -> `01010000` | `01010202` -> `00000101` |

Every entry moves the same way. 0x1080 differs in absolute value only because
the two model families carry different padding, tflite SAME against a symmetric
ONNX pad, and **the delta is self consistent on each side**. Weight buffer sizes
are right too: 73728 bytes for the 3x3 and 204800 for the 5x5, both matching
`k*k*oc*ALIGN(ic,32)*2`, with the DMA count in 0x101c matching the bytes
actually written in each case.

So for k=3 the registers are right, the buffer size is right, and the MAC very
nearly cancels. The remaining payload surface is the **order of bytes inside**
the weight buffer, which has only ever been verified for 1x1.

**The probe for that is not trustworthy yet, and I am not reporting its output
as a finding.** `posprobe_k.py` gives every weight a value depending only on
(ky, kx) so each spatial plane becomes one repeated byte. It reports the first
five 256 byte blocks holding planes 0, 2, 4, 6, 8, and the odd planes appearing
nowhere in the file. That reproduces with weight compression disabled and a
kernel that is not rank one, so it is not a compression artifact, but two things
make it unsafe to build on:

- a kernel constant across `ic` and `oc` is a degenerate tensor and the toolkit
  is free to restructure it
- the block identifier samples a single byte per 256, which stops meaning
  anything as soon as the weights carry any jitter

**Next**: redesign it so each plane is identifiable without being constant, for
instance a distinct value range per plane with per (oc, ic) variation inside the
range, and confirm the recovered order against the 5x5 case that is known to
work before trusting anything it says about 3x3.

## 2026-08-08 round 15 (Requant EXCLUDED for the flat family, and the three cases fail in three different ways.)

**The md003 family is not a requant bug.** `ROCKET_OUT_SHIFT_ADD` moved the
OUT_CVT shift from 23 to 21 and then to 17, both confirmed emitted in the log,
and the output was byte identical both times. A 64x change in the requant scale
moves nothing, which is only possible if `MAC + A` is exactly 0.

**The first 64 outputs, against the CPU on the same generated input:**

| model | shape of the answer |
|---|---|
| `conv2d-cal`, 5x5 | `npu == cpu` wherever `cpu > out_zp`, `npu == out_zp` below it |
| `cal_k3`, 3x3 | `out_zp + 0..2` everywhere |
| `cal_k1`, 1x1 | wild, saturating to 0 and to 128 |
| `md003_80` | flat `out_zp` |

The first line is worth stating plainly because it is the first direct look at
what "correct" means here: **the hardware applies a ReLU at the output zero
point**, and above it the NPU agrees with the CPU exactly. That is why
`test_model.py` compares against `max(cpu, zp)`.

**This corrects round 14.** I described `cal_k3` and `cal_k1` as "computing a
wrong answer" because their output varied with the input. `cal_k3` varies by 0
to 2 counts above the zero point, which is a MAC that very nearly cancels, not a
wrong convolution. `cal_k1` is the only one producing large wrong amplitudes.

`job_log` was left out of round 15's script, so every `jobs=` column read 0.
That meant nothing; it is back on in round 16.

Round 16 dumps the regcmd for `cal_k3` and, as the pair, for `conv2d-cal`, which
is the same model one kernel apart. There are now vendor .rknn builds at exactly
both geometries (`g_cal_k3`, `g_cal`), so the round yields mesa against vendor at
k=3, and mesa against mesa across the kernel change, which is the method that
found both 0x1080 and 0x4050.

Spotted in the vendor builds and worth checking in that diff: the vendor stages
a **kernel dependent number of input rows**. At 80x80 stride 2 it uses 79 rows
for a 1x1 and 80 for a 3x3 and a 5x5 (`0x1028` high is `surf * rows`, `0x102c`
low is `rows - 1`). Mesa always uses the full input height whatever the kernel.

And a near miss to record: the vendor's `0x1080` for `g_cal_k3` reads
`00000101`, which looks wrong against mesa's `01010000` until you notice the
vendor model is an ONNX with symmetric pad 1, giving before 1 and after 0, while
tflite SAME at k=3 stride 2 on 80 gives a total of 1, so before 0 and after 1.
Both are right for their own model. **Check a vendor register against that
model's own padding, not against the tflite one.**

## 2026-08-08 round 14 (It IS the kernel size, proven on the model that works. And the failures split into two different modes, which nothing had noticed.)

`mutate_k.py` crops conv2d-cal's own kernel. Same file, same scales, same
shapes, only the kernel. Controls passed at both ends.

| model | kernel | result |
|---|---|---|
| `conv2d-cal` | 5x5 | 2/2 OK |
| **`cal_k3`** | **3x3, centre taps** | **0/3 FAIL** |
| **`cal_k1`** | **1x1, centre tap** | **0/3 FAIL** |
| `cal_k1` with the 3x3 rewrite | 3x3 | 0/3 FAIL |

So the kernel and the model are no longer confounded: **5x5 works, 3x3 and 1x1
do not, on one and the same model.**

**And the two families fail differently:**

| model | top1 across three inputs | stale |
|---|---|---|
| `cal_k3` | 109, 93, 349 | no |
| `cal_k1` | 1, 2, 0 | no |
| `md003_80` | 0, 0, 0, flat out_zp | **yes** |

`cal_k3` and `cal_k1` **vary with the input**. That is a computed answer that is
wrong, not a dead datapath. The md003 family returns a constant. And
`md003_oc128` is the same geometry as `cal_k1`, 1x1 with 16 in and 128 out, yet
one varies and the other is flat, **so geometry does not decide which mode, the
model does**. What differs there is the quantization: md003 has input zero point
0, output scale 0.317 and OUT_CVT shift 23, against 128, 32 and 25 for the
conv2d-cal family.

A flat out_zp is exactly what a requant that underflows to zero produces, which
would make the md003 family a requant bug with nothing to do with the kernel.
Round 15 tests that with `ROCKET_OUT_SHIFT_ADD`, and prints the first 64 outputs
of `cal_k3` and `cal_k1` so the wrong-but-varying answers can drive an offline
search over candidate weight orderings.

**The kh/kw transpose is excluded without a board run**: conv2d-cal's 5x5
kernel is not transpose symmetric, 40568 of 51200 bytes differ under it, and the
model computes byte exact. Mesa's kernel ordering is right at 5x5.

## 2026-08-08 round 13 (The knob DID fire, so round 12 stands: a genuine 3x3 conv fails too, with a regcmd that matches the vendor at that geometry.)

The control was a size, and the size moved:

| md003_80 weight buffer | bytes | md5 | first bytes |
|---|---|---|---|
| without the knob | 256 | `c6cc3072` | `b7 b4 dc 06 ...` |
| **with `ROCKET_PW_AS_3X3=1`** | **9216** | `799b978e` | **`fe fe fe fe ...`** |

`0xfe` is `wt_zp - 0x80`, the ring taps, exactly as designed. And the regcmd it
produces, against a vendor .rknn compiled at that same 3x3 geometry (16 in, 16
out, 80x80, stride 1):

| entry | mesa | vendor |
|---|---|---|
| CNA 0x1018 | `40000505` | `40000404` |
| CNA 0x1040 | `14000000` | `10000000` |
| DPU 0x40ac | `ffffffff` | `00000003` |
| DPU 0x40b4 | `00000017` | `00000019` |

The first two are the pair already shown inert on this very model, the last two
are requant fields for different scales. **A real 3x3 convolution, configured the
way the vendor configures one, returns a uniform out_zp.**

So it is not 1x1 encoding, and the rewrite is not a workaround. The table:

| | result |
|---|---|
| 5x5 stride 2, 128 out | OK |
| 5x5 stride 1, 128 out | OK |
| 5x5 stride 2, 16 out | OK |
| 3x3 stride 1, 16 out | FAIL |
| 1x1 stride 1, 16 and 128 out | FAIL |

**But the kernel and the model are still confounded**, because every failing
model came from somewhere other than `conv2d.tflite`. `mutate_k.py` (new) crops
conv2d-cal's own kernel to the centre 3x3 and 1x1, which per-tensor quantization
makes safe, and SAME padding holds the output at 40x40x128 either way. One
variable, off the model that works, the same shape of mutation that produced the
padding result.

| outcome | meaning |
|---|---|
| `cal_k3` and `cal_k1` fail | it is the kernel size, full stop |
| they pass | it is not the kernel, it is the models, and `conv2d.tflite` is special in a way nothing has tested |

The second would be the more useful answer and it is the one that has never been
checked.

## 2026-08-08 round 12 (UNINTERPRETABLE. The control I wrote cannot tell "the rewrite did not help" from "the rewrite never ran".)

| step | result |
|---|---|
| `conv2d-cal` untouched | 2/2 OK |
| `conv2d-cal` with `ROCKET_PW_AS_3X3=1` | md5 `80e64aab2f96`, unchanged |
| `md003_80` untouched | uniform 127 |
| `md003_80` with the knob | **byte identical**, `task_count=1` |
| `md003_oc128` with the knob | byte identical |
| `mn_pw2` with the knob | unchanged, still `task_count=2`, still 2 OUT_CVT lines |

The stated control was that a 5x5 must be untouched, and it was. **That control
is worthless here**, because "unchanged on a 5x5" is also exactly what "never
fires anywhere" looks like.

And nothing moved on the models it should have transformed. A 3x3 kernel costs
nine times the weight bytes and nine times the CBUF, so `mn_pw2` holding at
exactly two tasks with two OUT_CVT lines, and `md003_80` at one, is what a knob
that did not fire looks like. The code placement is right, the env plumbing in
the script is right, and neither of those is evidence.

This is the round 8 failure again: a control that cannot fail. Caught before
drawing a conclusion this time, which is the only difference.

The check is a size, not a value:

| path | weight buffer |
|---|---|
| 1x1 | `ic*oc` = 256 bytes |
| 3x3 rewrite | `9 * oc * ALIGN(ic, atom) * 2`, thousands |

Round 13 dumps it both ways. If the size does not move, round 12 measured
nothing. If it does move, then a genuine 3x3 conv with 16 in and 16 out at 80x80
**also fails**, which is a bigger fact than the one being tested: it would put
the failure on kernel size, with 5x5 working at both strides and 3x3 not, and
1x1 encoding would have nothing to do with it.

Round 13 also prints the regcmd under the knob, because a vendor .rknn compiled
on the host at exactly that geometry (16 in, 16 out, 80x80, 3x3, stride 1)
already exists to diff it against.

## 2026-08-08 round 11 (The DPU does not read the coefficient buffer either. For a 1x1 conv every payload and every comparable register is now accounted for, and it still emits only out_offset.)

The control could fail, and it moved:

| | mean | md5 | relu maxdiff |
|---|---|---|---|
| `conv2d-cal` untouched | 145.72 | `80e64aab` | 1 |
| `conv2d-cal`, A forced to 0x2000 | 149.45 | `cb4a71b8` | 17 |

So `ROCKET_ATEST` reaches the hardware. And `md003_80`:

| | result |
|---|---|
| untouched | distinct=1, uniform 127, md5 `f999f370e8b4` |
| A forced to 0x2000 | **identical md5** |
| A forced to 0x40000 | **identical md5** |

**So the DPU does not read the coefficient buffer for a 1x1 conv.** Put together
with the earlier rounds, a 1x1 conv is now fully accounted for and still broken:

| surface | state |
|---|---|
| regcmd | matches a vendor .rknn compiled at the same geometry |
| weight layout | matches the vendor's own compiled buffer (`posprobe_pw.py`) |
| weight contents | not read (`ROCKET_PW_WTEST`, control verified) |
| input | not reflected in the output, and the same input BO drives a 5x5 that computes |
| coefficient buffer / A | not read (`ROCKET_ATEST`, control that moved the working model) |
| 0x1018, 0x1040 | inert on this model, not just on `mn_pw24` |
| output BO | fully written by the DPU, with exactly `out_offset` |

Everything the driver produces is right and the block emits only the OUT_CVT
offset.

**So route around it instead of hunting further.** A 1x1 conv is exactly a 3x3
conv whose outer ring sits at the weight zero point: the MAC computes
`sum((in - 0x80) * (w - wt_zp))`, so a tap with `w == wt_zp` contributes nothing,
and that holds for the SAME padding taps at the border too, which makes the
rewrite exact rather than approximate. `ROCKET_PW_AS_3X3` synthesises that kernel
in `rkt_coefs.c` and widens the geometry in `rkt_ml.c`, so the op takes the 3x3
path that demonstrably works and every derived register follows.

| outcome | meaning |
|---|---|
| `md003_80` computes | the answer is right, and most of MobileNet is pointwise |
| `md003_80` stays at 127 | not the kernel encoding at all, and the 3x3 path cannot carry these values either |

The control that can fail is `conv2d-cal` with the knob on: it is 5x5, so the
rewrite must leave it untouched. And `jobs=` and `task_count` matter in this
round, because a 3x3 costs nine times the CBUF and may split where the 1x1 did
not.

## 2026-08-08 round 10 (The DPU does run for a 1x1 conv. It writes the whole surface, and what it writes is exactly out_offset.)

| raw BO, before teflon adds 0x80 | size | distinct | first bytes |
|---|---|---|---|
| `md003_80` output | 204800 | **2** | `ff ff ff ff ...` |
| `conv2d-cal` output, positive control | 409600 | 128 | `00 10 0e 00 ...` |
| both inputs | 204800 | 251 | `80 87 8e 95 ...` |

Not zero, so this is not the untouched-buffer trap. `0xff` is -1 signed, teflon
adds 0x80 and gets 127, and 127 is exactly the `out_zp` the test reports:

```
md003_80: distinct=1 mean=127.00 min=127 max=127   (zp=127)
```

**The DPU ran, wrote every byte of the output surface, and what it wrote is
`out_offset`.** So `MAC + A` arrived as exactly 0.

That is sharper than it looks, because A is not supposed to be 0. md003 has
input zero point 0, so A carries `-128*sum(w)`, and round 9 showed that dropping
that term changes nothing either. Either the DPU never reads the coefficient
buffer, or it does and A genuinely arrives as 0.

Round 11 forces A directly with `ROCKET_ATEST=<value>`, at two values so a
coincidence at one is visible. `requant(0 + A)` with a large A has to saturate
the output away from `out_zp`:

| result | meaning |
|---|---|
| output moves off 127 | the DPU reads the coefficients and the write path is alive, and the dead stage is specifically the CNA feeding the CMAC |
| output stays at 127 | the coefficient buffer is not read either, and the problem is upstream of the whole DPU input side |

The control is `conv2d-cal` with the same knob. It computes correctly, so
forcing A there **must** wreck its output. Round 8 shipped a control that could
not fail and cost a round; this one can.

## 2026-08-08 round 9 (Control works this time, so round 8 stands: a 1x1 conv's output depends on nothing in any of its buffers.)

| weight buffer | distinct | md5 | first bytes |
|---|---|---|---|
| plain | 125 | `c6cc3072` | `b7 b4 dc 06 ...` |
| `ROCKET_PW_WTEST=1` | **1** | `ec80de13` | `7f 7f 7f 7f ...` |

The knob fires. So the round 8 null result is trustworthy, and three separate
things change nothing about the output of `md003_80`:

| changed | output |
|---|---|
| every pointwise weight forced to 0x7f | byte identical |
| `ROCKET_CBUF_DERIVE=1`, the vendor's 0x1018 and 0x1040 | byte identical |
| `ROCKET_BIAS_NOSW=1`, drops -128*sum(w) from A | byte identical |

The second closes the gap flagged in round 8: 0x1018 and 0x1040 are inert on the
model they are actually wrong for, not just on `mn_pw24`. The third is not a
small perturbation, since md003 has input zero point 0.

**So a 1x1 conv's output depends on none of the weights, the input, or the bias
and A term**, while every comparable register matches a vendor .rknn compiled at
the same geometry and the weight layout matches the vendor's own compiled buffer.

That is stronger than "the MAC is dead", and it changes the question. A fresh
shmem BO is zeroed and teflon's readback adds 0x80, so **an output buffer that
was never written comes back as a uniform 128 and is indistinguishable from a
computed constant at the tflite level**. That trap has already cost this project
one retraction, in the A to B wall. Round 10 reads the RAW buffer instead, with
`conv2d-cal` as the positive control for what a buffer the hardware definitely
wrote looks like.

## 2026-08-08 round 8 (The 1x1 conv ignores its weights and its A term. But the control for that was worthless, so round 9 re-runs it with one that works.)

Controls held. Three runs of `md003_80` gave **byte identical output**:

| step | output |
|---|---|
| plain | raw 116, relu 71, top1 0, stale |
| every pointwise weight forced to 0x7f | **identical** |
| input zero point term dropped from A | **identical** |

Taken at face value: the CMAC does not read the weight buffer, and the A term is
not what pins the output to a constant.

**The control did not work.** It used `where.py`, which counts NONZERO bytes.
0x7f is nonzero and so is nearly every real weight, so a forced buffer and a real
one both read 100 percent, and the step could not tell whether the knob fired.
This project has a written rule against exactly that, the rule is quoted in the
same script, and the next line broke it. `bstat.py` (new) reports DISTINCT, which
discriminates, and round 9 dumps the buffer both ways.

**And a gap in the reasoning that got here.** 0x1018 and 0x1040 were called
inert on the strength of `mn_pw24`, which has 512 input channels at 7x7.
`md003_80` has never been run with them at the vendor value: mesa gives it
`40000505` and `14000000` where the vendor .rknn at that geometry has `40000404`
and `10000000`. It is a single task, so `ROCKET_CBUF_DERIVE=1` hands it the
vendor pair, and closing that on this model costs one step.

Round 9 is those two things: make the null result trustworthy or throw it away,
and close 0x1018 / 0x1040 on the model they are actually wrong for.

## 2026-08-08 round 7 (DPU 0x4050 confirmed with an A/B. Three geometries compute. And with the channel-count bug gone, the 1x1 conv is properly isolated.)

| step | result |
|---|---|
| `conv2d-cal` | 2/2 OK |
| **`cal_oc16`, derived `0x80011011`** | **3/3 OK, relu maxdiff 0, top1 exact** |
| **`cal_oc16`, `ROCKET_DPU4050_CONST=1`** | **0/3 FAIL, round 6's numbers exactly** |
| `md003_80`, 1x1 with 16 channels | 0/3 FAIL |
| `md003_oc128`, 1x1 with 128 channels | 0/3 FAIL |
| `cal_s1` | 2/2 OK, the padding fix holds |

**A prediction missed**: `md003_80` was called fixed and is not. Its numbers
did move (raw 117 / relu 70 to 116 / 71), so 0x4050 reached it and something
else is wrong too.

**Two bugs were superimposed, which is why round 6 could not read the kernel.**
With the channel-count bug gone the split is clean: every 5x5 conv computes,
every 1x1 conv fails. It was the kernel after all, and `cal_oc16` failing in
round 6 was the other bug.

**The 1x1 case is cornered.** Its regcmd, against a vendor .rknn compiled at the
same geometry, now differs only in 0x1018 and 0x1040 (both shown inert by their
own A/B) and 0x40ac and 0x40b4 (requant offset and shift, not comparable across
differently quantized models).

**And the weight layout is confirmed correct**, which had never been checked
against anything but a board capture taken while the wall was still up.
`posprobe_pw.py` (new) compiles a 1x1 conv whose every (oc, ic) pair carries a
distinct weight, finds the weight blob in the .rknn and reads back the order. It
is oc-major with ic contiguous, exactly what `rkt_coefs.c` writes.

So for a 1x1 conv the registers are right and the weights are right, and **the
output is constant across different inputs**. No weight value and no requant
error produces a constant. The input is not reaching the MAC.

Round 8 stops looking at values and asks what the block reads:

| probe | what a null result means |
|---|---|
| `ROCKET_PW_WTEST=1`, every pointwise weight forced to 0x7f | output unchanged means the CMAC never reads the weight buffer |
| `ROCKET_BIAS_NOSW=1`, drop the input zero point term from A | md003 has input zp 0 so that term is -128*sum(w); conv2d-cal has 128 and never exercises it |

with a step that dumps the weight buffer to confirm the first knob fired,
because a null result from a knob that did not fire has cost this project runs
before.

## 2026-08-08 round 6 ("It is the kernel" refuted by its own probes. The regcmd diff found the register instead: DPU 0x4050 depends on the output channel count.)

| step | result |
|---|---|
| `conv2d-cal`, 5x5, 128 channels | 2/2 OK |
| **`cal_oc16`, the SAME 5x5 conv cut to 16 channels** | **0/3 FAIL** |
| **`md003_oc128`, the 1x1 grown to 128 channels** | **0/3 FAIL** |
| `md003_80`, 1x1 with 16 channels | 0/3 FAIL |

Both mutants fail, so neither the kernel nor the channel count explains it on
its own, and the round 5 reading was too quick.

**The regcmd dump is what paid.** Mesa's stream for `md003_80` against a vendor
.rknn compiled at exactly that geometry, 143 entries against 139:

| entry | mesa | vendor | |
|---|---|---|---|
| CNA 0x1018 | `40000505` | `40000404` | already shown not to matter |
| CNA 0x1040 | `14000000` | `10000000` | already shown not to matter |
| **DPU 0x4050** | **`80011111`** | **`80011011`** | |
| DPU 0x40ac | `ffffffff` | `ffffffef` | requant offset, different quantization |
| DPU 0x40b4 | `00000017` | `00000018` | requant shift, same |
| 4 trailing op-enables | | | mesa's whole-graph trailer |

The last two are not comparable: the vendor model carries the toolkit's own
quantization, not md003's, so its offset and shift are for different scales.

**0x4050 depends on the output channel count**, swept with everything else held
fixed:

| output channels | 0x4050 |
|---|---|
| 16, 48, 80, 112, 144 | `80011011` |
| 32, 64, 96, 128, 160 | `80011111` |

Ten out of ten. The bit says whether the last 32-channel group is only half
full. Mesa emitted the 128-channel constant unconditionally, so it was right for
`conv2d-cal` and wrong for every conv whose channel count is 16 more than a
multiple of 32. `ROCKET_DPU4050_CONST=1` restores it.

**Predictions for round 7, stated before the run:** `cal_oc16` computes with the
derived value and fails with the constant; `md003_80` computes, because its diff
contained nothing else; **`md003_oc128` still fails**, since 0x4050 was already
correct for 128 channels. The last one is the useful one, isolating whatever is
left to a case where this register is right, and its regcmd gets dumped.

## 2026-08-08 round 5 (Two threads closed: the row-window split is not the discriminator, and 0x1018 / 0x1040 are not load bearing. It is the kernel.)

Controls held at both ends, and `cal_s1` kept its round 4 win across a reflash.

| step | result |
|---|---|
| `conv2d-cal` | 2/2 OK |
| `cal_s1` | 3/3 OK, the padding fix survives |
| **`md003_80`, 1x1 at 80x80, ONE row window** | **0/3 FAIL** |
| `md003` at 160x160, two windows | 0/3 FAIL, byte identical numbers |
| `mn_pw24`, stride-keyed 0x1018 / 0x1040 | 0/3 FAIL |
| `mn_pw24`, `ROCKET_CBUF_DERIVE=1` | 0/3 FAIL, **identical output** |
| `cal_s1` with `ROCKET_CBUF_DERIVE=1` | 2/2 OK, no regression |

**The row-window split is out.** `md003_80` runs as a single window at the same
size and input channel count where a 5x5 conv computes, and fails with the same
numbers as the split version.

**0x1018 and 0x1040 are out.** Turning the knob changed nothing on the one model
where the stride and the split disagree, and did not disturb the model that
computes. That was the stated expectation before the run, which is the only
reason to have shipped it as a knob rather than a fix.

**So it is the kernel.** With one loose end: `md003_80` and `cal_s1` also differ
in output channels, 16 against 128. `mutate_oc.py` (new) truncates or repeats the
filters, which per-tensor quantization makes safe, giving `cal_oc16` (the 5x5
conv cut to 16 output channels) and `md003_oc128` (the 1x1 grown to 128). Those
two separate it.

**The register set is probably not where the 1x1 bug lives.** The vendor .rknn
compiled at exactly this geometry, 1x1 with 16 in and 16 out at 80x80, differs
from the 5x5 one only in fields mesa already computes:

| reg | vendor 1x1 | vendor 5x5 | what it is |
|---|---|---|---|
| 0x1024 | `0000000f` | `0404007f` | kernel word, output channels - 1 |
| 0x1030 | `0020004f` | `0320004f` | weight bytes per kernel |
| 0x1080 | `00000000` | `02020202` | padding, correct on both sides now |

Everything else in the watched set is identical. So round 6 also dumps the whole
regcmd mesa emits for `md003_80`, to diff against the vendor's on the host. If
they match, the bug is in the weight or coefficient buffer rather than in a
register, which is a different kind of search.

## 2026-08-08 round 4 (CONFIRMED with an A/B in one boot: the padding fix makes a second geometry compute. Two now work, up from one.)

| step | 0x1080 | result |
|---|---|---|
| `conv2d-cal`, derived (identical to the old constant) | `02020101` | 3/3 OK |
| **`cal_s1`, derived** | **`02020202`** | **3/3 OK, relu maxdiff 1, top1 exact** |
| **`cal_s1`, `ROCKET_PAD_LADDER=1`** | **`00000000`** | **0/3 FAIL, round 3's numbers exactly** |
| `conv2d-cal` again | | 2/2 OK |

Same boot, same model, same input generator, one register apart. `cal_s1` had
never computed before. The control passing on both sides of the round and the
old value reproducing the old failure is what makes it a result rather than a
coincidence.

**Predictions that held**: the 1x1 convs `mn_pw2` and `md003` have padding 0
either way and stayed broken, exactly as stated before the run.

**A prediction that did not**: `mn_conv0` was listed as fixed by the derived
`0x01010000` and it still fails. 3 input channels take `fill_regcmd_firstconv`,
a different function that this change never touched, and it emits no `OUT_CVT`
line in the log for the same reason. Its failure is unexplained by anything
here.

**What is left, now that it splits cleanly:**

| thread | models | state |
|---|---|---|
| 1x1 kernel | `mn_pw2`, `md003`, `mn_pw24` | padding is 0 for them, so this is a different bug |
| row-window split | `mn_dw1`, `mn_pw2`, `md003` (task_count 2) | both working geometries are single-window |
| first-conv path | `mn_conv0` | separate function, untouched |

**0x1018 and 0x1040 are keyed off the stride and the vendor does not key them
off the stride.** A width and channel sweep flips both exactly where the op
stops fitting one row window: 16 channels at 128x128 is one window and reads
`40000404` / `10000000`, 144x144 splits and reads `40000505` / `14000000`, and
holding 80x80 while raising input channels flips at the same place (32 fits, 48
splits).

**But they tolerate being wrong.** `cal_s1` computes correctly with the
stride-keyed value where the vendor would use the other one. So this is a knob
to A/B (`ROCKET_CBUF_DERIVE=1`), not a fix to ship, and the honest expectation
is that it changes nothing.

Round 5 probes the 1x1 thread with `md003_80`, which is `md003` resized to 80x80
(`mutate_hw.py`, new; a 1x1 kernel is valid at any spatial size). That drops the
row-window split and leaves the kernel as nearly the only difference from a
model that computes, so it separates the first two threads from each other.

## 2026-08-08 round 3 (SOLVED: CNA 0x1080 is the PADDING register and mesa hardcoded it. That is why exactly one geometry has ever computed.)

Stride was refuted as a single variable (`cal_s1` failed as predicted, but
`md003_s2` failed too). The regcmd diff it produced is what mattered.

`conv2d-cal` against `cal_s1`, one model change, **14 differing entries of 143**.
Ten are plain geometry (0x27 = 40 - 1, 0x4f = 80 - 1, 0x640 = 1600, 0x1900 =
6400). Four are not, and in `rkt_regcmd.c` all four are `s == 2 ? A : B` with
constants fitted to the captures this project happens to own:

| reg | conv2d-cal, computes | cal_s1, does not |
|---|---|---|
| CNA 0x1014 | `00000012` | `00000009` |
| CNA 0x1018 | `40000404` | `40000505` |
| CNA 0x1040 | `10000000` | `14000000` |
| **CNA 0x1080** | **`02020101`** | **`00000000`** |

**Host-side vendor data settles it.** The toolkit compiles .rknn on this machine
from ONNX, so vendor register values are available at any geometry without a
board (`vendor-capture/gen_geom.py`, `ladder.py`, both new). Direct test, k=5
stride 1 on 80x80, varying only the ONNX pad:

| pads | vendor 0x1080 |
|---|---|
| 0 | `00000000` |
| 1 | `01010101` |
| 2 | `02020202` |

and the asymmetric pair says which half is which: `conv2d.onnx` (before 1, after
2) gives `02020101`, the same geometry with symmetric pad 2 (before 2, after 1)
gives `01010202`. The vendor's tiled depthwise gives `01000101` on the first row
window and `01010100` on the last, which is the top pad only at the top and the
bottom pad only at the bottom.

```
0x1080 = (pad_right << 24) | (pad_bottom << 16) | (pad_left << 8) | pad_top
```

**`0x02020101` is tflite SAME padding for a 5x5 stride-2 conv.** It is
conv2d-cal's own padding, lifted from the capture the branch was fitted to. So
a stride-1 conv was configured with no padding at all, and every other stride-2
conv was configured with 5x5's. **That is the explanation for the whole table:
one geometry computes because one geometry's padding is compiled in.**

The fix needs no new arithmetic: `rkt_split_tasks` already computes
`pad_top/bottom/left/right` per task, windowing included, and the RK3576 path
simply never read them. It does now. `ROCKET_PAD_LADDER=1` restores the old
constants, so the round carries its own A/B.

conv2d-cal's derived value is `0x02020101`, identical to the constant, so the
control is also a check that the change is a no-op where it was already right.

**This does not fix the 1x1 convs.** Their padding is 0 either way, so
`mn_pw2`, `mn_pw24` and `md003` should stay broken. Their bug is 0x1018 and
0x1040, which a width sweep shows the vendor keys off whether the input fits the
CBUF (`0404`/`10000000` up to 112x112x16, `0505`/`14000000` at 160x160 where the
op tiles) while mesa keys them off the stride. That is the next thread.

## 2026-08-08 round 2 (Both hypotheses refuted by their own probes. The headline is simpler and worse: conv2d-cal is the ONLY convolution geometry this driver has ever computed correctly.)

Controls held at both ends of the round, 3/3 first and 2/2 last.

| probe | what it changed | task_count | result |
|---|---|---|---|
| `conv2d-cal` control | - | 1 | 3/3 OK |
| `cal_ozp0` | out_zp 128 -> **0** | 1 | **3/3 OK**, raw maxdiff 1 |
| `cal_izp0` | in_zp 128 -> **0** | 1 | **3/3 OK** |
| `pw2_zp128` | mn_pw2, both zp -> 128 | 2 | 0/3 |
| `mn_pw24` | MobileNet op24, 1x1 on 7x7x512 | **1** | 0/3 |
| `mn_dw25` | MobileNet op25 depthwise, 7x7 | **1** | 0/3 |
| `md003` | 1x1, **16 in / 16 out ch**, out_zp 127 | 2 | 0/3 |
| `conv2d-cal` again | - | 1 | 2/2 OK |

**A is dead**: conv2d-cal computes with its output zero point forced to 0, and
with its input zero point forced to 0. **B is dead**: `mn_pw24` and `mn_dw25`
each submit a single task and still fail. `md003` kills the channel-count idea
too, being 16 in and 16 out like the model that works.

So four single variables are now refuted with their own controls: quantization
regime, zero point, task split, channel count.

**What the table actually says.** Only `conv2d-cal` and its twin `conv2d.tflite`
have ever been correct, and they are the same geometry: 80x80x16 in, 5x5 kernel,
**stride 2**, 128 output channels, one task. Every failing model is **stride 1**,
except `mn_conv0`, which takes the separate first-conv path on 3 input channels.
"Regular conv works" was always a claim about one configuration.

Round 3 tests stride the same way, by changing only that (`mutate_stride.py`,
new; SAME padding makes the output ceil(in/stride), which it resizes):

| probe | stride predicts |
|---|---|
| `cal_s1`, conv2d-cal 5x5 stride 2 -> 1 | FAIL |
| `md003_s2`, md003 1x1 stride 1 -> 2 | PASS |

Both must flip. It also dumps and decodes the regcmd mesa emits for
`conv2d-cal` and for `cal_s1`, which are one variable apart, so the round
produces a readable register diff whatever the verdict. That is the input to the
vendor comparison: the wall was broken by diffing an ordered register trace
against the vendor's, not by guessing which knob mattered, and model-space
bisection has now spent two rounds.

Probe flaw to not repeat: both control steps ran the same model, so they wrote
the same `/dev/kmsg` marker and the second one's dmesg slice replayed the first
one's `task_count` lines. The run lines themselves were fine. Markers are now
per step, not per model.


## 2026-08-08 round 1 (My own regime hypothesis is REFUTED, and what replaces it is much narrower: a plain 1x1 uint8 conv fails in one job.)

Control passed, hypothesis died, and the table got sharper.

| model | ic | oc | in HxW | in_zp | out_zp | tasks | result |
|---|---|---|---|---|---|---|---|
| `conv2d-cal` | 16 | 128 | 80x80 | **128** | **128** | **1** | **3/3 OK** |
| `mn_pw2` 1x1 | 32 | 64 | 112x112 | 0 | 0 | 2 | 0/3, output follows the input |
| `mn_conv0` 3x3 s2 | 3 | 32 | 224x224 | **128** | 0 | ? | 0/3, output follows the input |
| `mn_dw1` depthwise | 32 | 32 | 112x112 | 0 | 0 | 2 | 0/3, constant |
| `mn_conv0dw1` | | | | | | 2 jobs | 0/3 |
| `dwconv` int8 per-axis | 16 | 16 | 40x40 | -1 | -29 | 1 | 0/3 |

**`mn_pw2` and `mn_conv0` are uint8 per-tensor plain convs and they fail**, so
the int8/per-axis story from earlier today is not the explanation. It stands as
a reason those two models were bad probes, and nothing more.

What the round bought instead: **the minimal failing case is now a 1x1
convolution, uint8 per-tensor, one job.** No depthwise, no chaining, no padding,
no per-axis. And `mn_pw2`/`mn_conv0` produce output that changes with the input,
so the block computes; it computes wrongly.

It also corrects the "one 256-byte atom" shape. `mn_dw1`'s output BO is 802816
bytes and `where.py` finds **one run of 401408 from offset 0**, exactly the
tensor size, fully written. The surface is complete and constant, not truncated.
The 256-of-51200 reading belongs to `dwconv` alone.

**Two variables survive, and every failing model changes both at once:**

- **A, the output zero point is 0** where the only passing model has 128.
  MobileNet quantizes every activation at zp 0. Mesa carries
  `unsigned offset = output_zero_point - 0x80` in `rkt_regcmd.c:715`, which for
  zp 0 is `0xffffff80` rather than -128, and `input_zero_point == 0x0` already
  has a special case at line 948.
- **B, the job splits into 2 tasks.** `conv2d-cal` emits one `OUT_CVT` line and
  one regcmd; `mn_pw2`, `mn_dw1` and `mn_conv0dw1` each emit two. `jobs=1` in
  the run lines counts submits, not tasks, so this was invisible until the
  regcmd dump showed `mesa-regcmd-000-000.bin` and `-001.bin`.

Round 2 separates them, because A and B make opposite predictions on all four
new probes. `mutate_zp.py` (new) rewrites activation zero points and leaves
geometry, weights and scales alone, so the task count is preserved; the small
MobileNet layers keep zp 0 and drop the task count:

| probe | A predicts | B predicts |
|---|---|---|
| `cal_ozp0`, conv2d-cal with out_zp 128->0 | FAIL | pass |
| `pw2_zp128`, mn_pw2 with both zp 0->128 | PASS | fail |
| `mn_pw24`, MobileNet op24 1x1 on 7x7x512, zp 0 | fail | PASS |
| `md003`, in_zp 0 but out_zp 127 | pass | - |

The CPU reference is recomputed from the same mutated file, so each probe asks
"does this configuration compute", not "does it match the original model".

`STALE` on `mn_dw1` and `mn_dw25` is not the wall coming back: their output is
a constant, so identical bytes across different inputs is what a constant looks
like. `mn_pw2` and `mn_conv0` are not stale.


## 2026-08-08 (The two small failing models are in a quantization regime the working one never touches. Correct as far as it goes, but see the board round above: it is not why they fail.)

No board run. Reading the model files and the Mesa source.

**`dwconv.tflite` is not what it says it is.** Its build script comment claims
"uint8 I/O (conv2d-cal's PROVEN regime)", and the entry below records it as one
standalone `DepthwiseConv2D`. Parsing the flatbuffer (`vendor-capture/tfl_ops.py`,
new) says otherwise:

| model | ops | the conv's tensors | weights |
|---|---|---|---|
| `conv2d-cal.tflite`, **correct on hw** | 1 CONV_2D | **u8**, zp 128 / 128 | **per-tensor**, zp 133 |
| `dwconv.tflite`, wrong | **3**: QUANTIZE, DEPTHWISE_CONV_2D, QUANTIZE | **i8**, zp -1 -> -29 | **per-axis**, 16 scales |
| `conv2x.tflite`, wrong | **4**: QUANTIZE, CONV_2D, CONV_2D, QUANTIZE | **i8**, zp -1 -> 4 | **per-axis**, 16 scales |
| `mobilenet_v1_1.0_224_quant.tflite`, wrong | 28 | **u8** | **per-tensor, zero per-axis tensors** |

TFLite's converter wrapped the model in QUANTIZE ops and made the interior int8
per-axis; `inference_input_type=uint8` only sets the boundary. So both small
failing models differ from the working one in **two** ways that have nothing to
do with depthwise or with chaining, and `conv2x`'s two ops are plain convs, not
depthwise at all.

**Mesa's int8 handling is wrong in two places, both visible in the source:**

1. `rkt_ml.c` writes `map[n++] = input_in[...] - 0x80` and pads with
   `zero_point - 0x80` unconditionally. `is_signed` is plumbed all the way from
   `tfl_device.c` and then never consulted here. An int8 tensor is already in
   the signed domain, so it gets shifted a second time.
2. `pipe_tensor::zero_point` is `int` and legitimately negative for int8; the
   Rocket driver copies it into `unsigned` (`rkt_operation`) and `uint8_t`
   (`rkt_task`). dwconv's input zp -1 becomes 255 where the hardware wants 127,
   and its output zp -29 becomes 227 where it wants 99. 99 is exactly the zp
   TFLite gives the same tensor in its u8 view, which confirms the +128 mapping.
   Everything downstream inherits it: the CNA pad value, `out_offset`, and
   `DPU_BS_OW_OP(0x80 - weights_zero_point)`.

Per-axis itself is handled, and deliberately: `rkt_coefs.c` emits the relative
per-channel `C[oc] = round(2^14 * wt_sc[oc] / max(wt_sc))` and `rkt_ml.c`
collapses the scales to their mean for the global OUT_CVT. For a per-tensor conv
every scale is equal, so `C = 0x4000` everywhere and the mean is exact. **That is
why `conv2d-cal` passing says nothing about the per-axis path.**

**Consequence.** "The depthwise datapath is broken" and "chained ops fail on
op2" were both read off models that also change regime. The June intent behind
`dwconv.tflite`, isolating the depthwise, was never actually achieved.

**What replaces them.** `vendor-capture/slice_tflite.py` (new) cuts a run of
operators out of a model into a standalone one, so single MobileNet layers can
run in their real regime with the real weights and no converter in the loop:

| new model | what it is |
|---|---|
| `mn_conv0` | MobileNet op0, CONV_2D 3x3 s2, 3 channels, u8 per-tensor |
| `mn_pw2` | MobileNet op2, CONV_2D 1x1 32->64, u8 per-tensor |
| **`mn_dw1`** | **MobileNet op1, DEPTHWISE_CONV_2D 3x3 on 112x112x32, u8 per-tensor** |
| `mn_conv0dw1` | ops 0 and 1 chained, both u8 per-tensor |

All four validated against the CPU interpreter on the host (`mn_dw1` distinct=256,
mean 99.96, so the reference is not degenerate). `mn_dw1` is what `dwconv.tflite`
was meant to be. The board round queues them behind `conv2d-cal` as the control
and keeps `dwconv.tflite` last for continuity, with `job_log=1` throughout so a
run the delegate quietly handed back to the CPU shows up as `jobs=0` instead of
passing.


## 2026-08-07 last (Depthwise: the write is ONE contiguous 256-byte run at offset 0, and the units end in a different state than a conv that completes.)

`where.py` on the dumped buffers, with the script's own control passing:

| buffer | nonzero | structure |
|---|---|---|
| depthwise output | 256 of 51200 | **1 run, offset 0, length 256** |
| depthwise input | 25498 of 51200 | 102 runs, stride 251 |
| conv output, reference | 101946 of 409600 | 51864 runs, out to offset 204799 |

So it is a **sequential stop**, not a channel-bank truncation: a banked
truncation would be strided, the way the input is. The control matters here, the
same script sees full writes on the other two buffers.

`dwconv.tflite` is confirmed to be one standalone `DepthwiseConv2D`, 40x40x16,
3x3 same, with bias (`vendor-capture/build_dw.py`). That model was built in June
specifically to separate the depthwise datapath from the chained-input question,
and its own comment says "if it ALSO zeros, the dw datapath itself is broken".
It zeros, and now, with the wall gone, that reading is trustworthy.

**Unit status at completion:**

```
conv, computes correctly    cna=0000000c  core=0000000c  raw=30000000
depthwise, stops at 1 atom  cna=00000005  core=00000005  raw=30000000
```

Do not decode these with `rocket_registers.h`. That header is RK3588 derived
and its field layout is already proven wrong for RK3576 on TASK_CON; it marks
bits 2 to 15 of S_STATUS as reserved, and bits 2 and 3 are exactly where these
two values differ. As speculation only: if RK3576 packs two bits per ping-pong
group, the conv ends with group1 = 3 and the depthwise with both groups = 1,
which would be stalled rather than done.

**The narrow question is now: why does the write stop after one atom.**

## 2026-08-07 later (Depthwise: the regcmd matches the vendor on every mode register, and the DPU writes exactly 256 bytes of a 51200 byte output and stops. Two of my own readings of this corrected by finally dumping the buffers instead of inferring from them.)

**The regcmd is not the difference.** Decoding our depthwise regcmd on the board
with mesa's own dump and comparing it three ways, our conv (which computes
correctly) against our depthwise against the vendor's depthwise capture:

Every depthwise mode register in ours matches the vendor's and differs from our
conv: `CNA/100c=1`, `1014`, `1018`, `1024`, `1040`, `CORE/3018`, `DPU/400c`,
`4038`, `4044`, `4050`, `RDMA/501c`, `5044`. The depthwise branch is configuring
the block the way the vendor does.

**Do not read the vendor capture's zeros as differences.**
`vendor-capture/vendor_dw_regcmd.txt` was extracted from a **static .rknn file**,
where address registers are unpatched placeholders. That accounts for all of
`CNA/1088`, `CNA/1110`, `DPU/4018`, `RDMA/5020` and `RDMA/5024` reading 0 on the
vendor side. Read as differences they would have suggested the vendor's depthwise
does not use the weight DMA at all, which is false.

After removing geometry (our model is 40x40x16, the capture is 112x112x32) and
those addresses, **exactly one difference remained**:

```
CNA 0x1080    our conv 02020101    our dw 01010101    vendor dw 01000101
```

mesa's own comment calls `0x01010101` "a mesa invention the vendor NEVER emits"
and ships `ROCKET_DW_SURF0` to force the vendor value. **Refuted with a passing
control**: the emitted regcmd confirms `01010101` -> `01000101`, and the output
md5 is `c5fe415451bf` both ways. That byte does not gate the compute.

**What the buffers actually contain**, from mesa's dumps rather than from
inference:

| buffer | size | contents |
|---|---|---|
| input | 51200 | 25702 zeros plus a spread, same shape as the working conv's |
| weights | 576 | filled as documented; the tail is unused and that is correct |
| biases | 33152 | mostly zeros plus a spread |
| **output** | **51200** | **50944 zeros and 256 bytes of one value** |
| conv output, for reference | 409600 | 307654 zeros and a real distribution |

**So the DPU writes exactly 256 bytes and stops.** 256 is one output atom on this
block. The depthwise op starts, emits a single atom, and goes no further.

**I got this wrong twice before dumping.** First I concluded "the op does not
run at all", from the fact that neither the weights nor the input change the
output. Then I corrected that to "the DPU does write", from the output tensor
holding 0 and the zero point rather than 128. Both were inferences from the
readback. The buffer dump settles it: 256 bytes of 51200. Dump the buffer, do
not reason about what the readback implies about it.

The weight buffer being 576 bytes with 288 of them zero is **not** a bug. mesa
documents block = DIV_ROUND_UP(channels, 2) * 4, which is 64 bytes for the
32-channel layers in the comment and 32 bytes for our 16-channel model, so 9
blocks is 288 bytes. The BO is allocated at 576 and `CNA/0x101c`, the weight
length, is programmed to `0x120` = 288. Consistent.

**Next question, and it is a narrow one**: why does the depthwise write stop after
one output atom. This has the same shape as the June "channel-bank truncation"
note about conv0, which was recorded when the wall made every such reading
unreliable and is worth re-testing now that it is not.

## 2026-08-07 late (Depthwise reads NEITHER its weights NOR its input: the op does not run at all, so it is not a weight-layout problem. Plus the bandwidth-counter instrument failed its own control three times, and a June reading of the 0x2210/0x2410 writes was wrong.)

**Depthwise ignores its weight buffer, with a passing positive control.** mesa's
`ROCKET_DW_WTEST` fills the whole depthwise weight buffer with 0x7f. The control
for whether the knob actually ran is mesa's own post-memset dump, enabled with
`ROCKET_DEBUG=dump_bos`:

| | first 32 bytes | distinct byte values |
|---|---|---|
| plain | `ff 9a 80 80  cc ff 80 80  dd 3f 80 80 ...` | 106 |
| WTEST | `7f 7f 7f 7f ...` | **1** |

The knob ran. The output md5 is `c5fe415451bf` **both times**. Note also that
the plain dump matches the layout mesa documents, two channel bytes then two
weight-zero-point pad bytes, so the weights are staged exactly as intended and
simply not consumed.

**Depthwise also ignores its input.** This was already in hand from the earlier
`test_model.py` run: three runs with three DIFFERENT inputs, and runs 1 and 2
flagged STALE, byte identical to run 0.

**So the op is not running.** It is not "the weights land in lanes the CMAC
ignores", which is what mesa's comment hypothesised. Nothing it reads changes
anything it writes. The output is `distinct=2`, values 0 and the output zero
point, regardless of both buffers, and with the poll disabled two of three runs
time out, which is what an op that never finishes looks like. The next thing to
look at is the CNA and CORE depthwise-mode configuration, before any buffer is
read.

**The bandwidth counters failed their own control three times. Do not reuse
this instrument without fixing it first.** The plan was: a regular convolution
computes correctly, so its `wt_rd` must be nonzero, and only then does a zero
from depthwise mean anything.

| attempt | result |
|---|---|
| readout in `rocket_job_handle_irq()` | logged one stray line: with the poll on, jobs retire through `rocket_poll_work_fn()` and that function is never called |
| readout moved to the shared locked helper | separation now correct, but the control conv still reads `wt_rd=0` |
| counters armed first, `0x80000101` then `0x00000101` on +0x210 and +0x410, as the June fork does | control conv still reads `wt_rd=0` |

Only `core +0x438` moves at all: 72 for the convolution, 0 for the depthwise. So
something is being read, but not the mapping the fork's format string claims.
`dmesg -C` does not clear the buffer on this busybox, which made the first two
attempts print the same line twice; use a marker written to `/dev/kmsg` and read
what follows it.

**Correction to a June reading.** The `0x2210` and `0x2410` writes
(`0x80000101` then `0x00000101`) that FINDINGS recorded as "two extra unit-enable
pulses rocket issues and the vendor does not, and rocket NEEDS them, drop them
and units do not engage even on op0" are **the bandwidth counter clear pulses**.
Offset 0x2210 from the NPU base is the stats page at 0x27702000 plus 0x210, not
an NPU unit register. The vendor trace lacks them because the vendor was not
counting. The claim that rocket needs an extra engage step rests on that
misreading and has to be re-tested.

## 2026-08-07 (THE WALL IS BROKEN. Root cause: PC_TASK_CON field layout, RK3576 uses a 16-bit task number. Plus: the "completion interrupt never reaches the GIC" claim in v1 through v6 is WRONG, and what is left are two ordinary per-op bugs.)

**Root cause.** `rocket_registers.h` is RK3588 derived and lays PC_TASK_CON out as
TASK_NUMBER bits 0..11, TASK_PP_EN 12, TASK_COUNT_CLEAR 13, RESERVED_0 14.
**RK3576 uses a 16-bit task number**, so those three controls sit at bits 16, 17
and 18.

| | value written to 0x0030 |
|---|---|
| rocket, v1 through v6 | `0x00007001` |
| vendor on RK3576 | `0x00070001` |

RK3576's PC therefore read rocket's word as **task_number = 0x7001, 28673 tasks**,
with TASK_COUNT_CLEAR landing on nothing. A count clear that never lands is
exactly "one task per reset": only a reset ever cleared the counter.

Fix: `rocket_pc_writel(core, TASK_CON, (0x7u << 16) | 1);`

**Board proof, one boot, control first** (`rocket.task_con16`):

| | 2nd submit, new input |
|---|---|
| task_con16=0, control | WRONG, crc unchanged `20a556ae` |
| task_con16=1 | **OK, maxdiff 1, crc moves to `dda67317`** |

and A -> B -> A' with B a genuinely different configuration:
**A ok, B ok `maxdiff=0 exact=100.0%`, A' ok.** First time since June.

**How it was found.** An ordered writel trace of the CURRENT rocket, in the same
format as the vendor's `rknpu.wtrace` (the register defines are already absolute
offsets so the two align without translation), diffed against
`dirty/vendor_wt.trace`. **Exactly one value differed in the whole submit.** Not a
guess: two guessed hypotheses the same evening, per-job IOMMU teardown and the
vendor post-completion sequence, were both refuted first.

**The fix already existed.** `kernel/0012` in the June fork carries it with a
full explanation. It was never carried into the upstream RFC series, so v1
through v6 all shipped `0x7001`. Diff the fork patches against the series before
concluding that anything is unexplained.

**Igor Paunovic named the mechanism** on the v5 thread: "a counter that still
reads non-zero on the walling submit would say the TASK_COUNT_CLEAR pulse that
hw_submit issues on every submit is not landing on RK3576". Right mechanism; the
register-level reason is the bit positions.

---

### The completion interrupt works. The claim in v1 through v6 is wrong.

With the TASK_CON fix and the poll disabled at runtime (`rocket.no_poll=1`), so
that only a real interrupt can retire a job:

  conv2d-cal, 3 runs, a different input each: **3/3 correct, 0 timeouts**,
  `/proc/interrupts` counting up on the NPU line.

So "the DPU completion interrupt is armed exactly as on RK3588 but never reaches
the GIC" is false. It reaches the GIC. It did not fire before because the PC
believed it had 28672 tasks left and never finished the sequence.

What DOES still time out is jobs that compute wrongly, which is coherent: the
completion fires when the DPU finishes writing, and a misconfigured op never
finishes. So a bounded poll is still worth having as a fallback, but the
justification has to change from "the interrupt does not arrive" to "a job that
fails to complete would otherwise sit until the 500 ms scheduler timeout".
Diederik de Haas privately warned that the poll reads as a workaround for an
undetermined problem and could significantly delay mainline. He was right, and
the underlying problem is now determined.

---

### What is left: two ordinary per-op bugs, and the dividing line is NOT the job count

| model | jobs per invoke | poll on | poll off | result |
|---|---|---|---|---|
| conv2d-cal | 1 | 0 timeouts | 0 timeouts | **3/3 correct** |
| conv2x, two chained convs | 2 | 0 | 3 | 0/3, STALE |
| **dwconv, depthwise** | **1** | 0 | 2 | 0/3, STALE |
| mobilenet_v1_224_quant | 28 | 0 | 12 | 0/3, STALE |

**dwconv is a single job and it fails**, so the split is not "one job works, many
jobs do not". It is:

- **regular int8 convolution: correct** (this is what the 2026-06-27 requant work
  fixed, and it survives the TASK_CON change);
- **depthwise convolution: wrong**, with no dispatch or chaining involved;
- **chained ops: the second op fails**;
- MobileNet has both, so it cannot work until both are fixed.

STALE on runs 1 and 2 of every failing model means the output buffer is not
rewritten across runs, which is what a job that never completes looks like.

**Oracle bug in this run's first pass, third of its kind:** `test_model.py`
compared against the raw CPU output and reported conv2d-cal as failing at maxdiff
128, when `test_once.py` had it byte exact. The hardware applies a ReLU at the
output zero point, so the reference is `max(cpu, zp)`. The script now prints both
and judges on the smaller. Copy the reference from a test that already passes
rather than writing a new one.

**Everything above this entry, from June onward, was chasing a symptom.** The
excluded results (writel values, register order, regcmd payload, power and reset
teardown, IOMMU churn, ping-pong) were all true and all irrelevant: they compared
against a driver that was asking the hardware for 28673 tasks.

## 2026-08-07 (Vendor control REDONE and it holds: the vendor really does recompute on every warm submit. Two rocket-side hypotheses tested and both REFUTED, controls clean. Plus: the vendor two-submit test had the same flawed oracle we retracted, and one of tonight's "new" ideas had already been run in June.)

**The vendor control was re-run with a different input per run, and the July
conclusion survives.** `runner_multi.c` staged the input ONCE before the loop and
fired `rknn_run()` five times over it, so "all five byte identical" could not
distinguish a recomputation from an untouched buffer. That is the same
non-discriminating test retracted for the open stack on 2026-08-06. Moving
`rknn_inputs_set()` into the loop with a per-run offset:

| run | crc (FNV) | |
|---|---|---|
| 0 | `01595b9e` | baseline, matches the simulator golden |
| 1 | `eca7ae23` | DIFFERS |
| 2 | `fdd239af` | DIFFERS |
| 3 | `ee6b0ec5` | DIFFERS |
| 4 | `06796b51` | DIFFERS |

Gaps 443/68/68/68 ms against a 3 s autosuspend, so one power session. The
post-idle control repeated run 0's input and reproduced `01595b9e` exactly.

**So the asymmetry is real: the vendor recomputes on every warm submit, rocket
computes once per reset.** The wall is rocket specific, not normal behaviour for
this block. Note the verdict logic in `run-twosubmit.sh` had to be rewritten
too: with a varying input `all_equal` means the OPPOSITE of what it meant before,
and left alone the script would have printed a confident wrong conclusion.

**Infrastructure trap that cost a boot:** the vendor 6.1 kernel needs the
Rockchip BL31 with OP-TEE, which serves the SCMI clock, power and reset
protocols. The board boots from **SPI**, and with the mainline U-Boot there
(TF-A v2.14.0, no OP-TEE) the vendor kernel gets `SCMI protocol 17 not active`,
`protocol 22 not active` and then `-71` on `clk_prepare` for rk-crypto and RKNPU
alike. The SD card's `rock4d-sd-uboot-vendor.img` is never used, SPI wins. Flash
`rock4d-spi-uboot-vendor.img` for vendor runs and `rock4d-spi-uboot.img` back for
rocket runs.

**Hypothesis 1, per-job IOMMU teardown: REFUTED.** rocket calls
`iommu_attach_group()` in `rocket_job_run()` and `iommu_detach_group()` when the
job retires, so it rebuilds the domain between every submit. The vendor's writel
trace shows no IOMMU touch between warm submits. `keep_domain=1` attaches only
when the domain changes and never detaches on completion, which makes
consecutive submits from one fd look like the vendor's. Result: identical to the
control, `20a556ae` / `20a556ae` / `dda67317` both ways. Not the wall.

This also corrects a claim in the July PINNED-SPREAD record, which said pinning
power removed the "IOMMU re-attach". It did not. Those two calls are in the JOB
path, not the runtime PM path, and ran regardless.

Worth keeping anyway: it removes a real per-job teardown and fixes a reference
leak, since the old detach passed `iommu_group_get(core->dev)` and never put it.

**Hypothesis 2, the vendor's post-completion sequence: REFUTED, AND IT HAD
ALREADY BEEN RUN.** The vendor trace (`dirty/vendor_wt.trace`, seq 17-22) does
this after every completion:

```
0x0024 = 0x0001ffff   irq handler
0x0008 = 0x00000000   OPERATION_ENABLE off
0x0024 = 0x30000000   clears PC_DONE, bits 28 and 29
0x1004 = 0x0001000e   CNA S_POINTER
0x1004 = 0x0001000f
0x1004 = 0x0001000f
```

rocket clears `0x1ffff` only, which does not reach bits 28 and 29, and never
touches S_POINTER after a job. Replayed verbatim as `vendor_post=1`, with the
parameter read back to confirm it applied: identical to the control.

**`dirty/rocket_wt.trace` already shows the June fork issuing
`0x1004 = 0x1000e / 0x1000f / 0x1000f` post-completion**, plus the DPU-side
`0x4004` equivalents, and FINDINGS already recorded `pp_alt` as a true negative.
The file was in the tree the whole time. This was proposed as unexplored without
checking it, and it cost a build and a flash. Read `dirty/*.trace` before
proposing anything that touches the per-submit register stream.

**Where this leaves the wall.** Excluded so far: register values (writel audit),
register order (ordered trace), regcmd payload (Kiln replay of the vendor's exact
bytes), power and reset teardown (pinned spread), per-job IOMMU domain churn, and
the post-completion PC_DONE clear plus S_POINTER re-arm. The only known lever is
still a core reset, which re-arms, while the vendor never resets and re-arms
anyway.

**Next, and it needs no board time:** capture a fresh ordered writel trace from
the CURRENT rocket, and align it against the vendor's second submit line by line.
The rocket trace we have is from a June fork with several experiments layered on
top, so it cannot be diffed directly. That enumerates what is left instead of
guessing at it one register at a time.

## 2026-08-06 (THE WALL IS POSITIONAL AFTER ALL: only the FIRST submit after a reset computes. Every "same op re-runs byte exact" result since June was a stale output buffer. Control passed in both directions.)

One config, two inputs, one latched output BO, checksummed read-only:

| step | result | crc32 |
|---|---|---|
| 1 A(input X), first submit of the session | OK, maxdiff 1 | `20a556ae` |
| 2 A(input Y), no reset in between | WRONG, maxdiff 127 | **`20a556ae`** |
| 3 A(input Y) again, after idling past the 50 ms autosuspend | OK, maxdiff 1 | **`dda67317`** |

Step 3 moves the checksum, so it demonstrably sees the block's writes. Step 2
does not move it, with the same configuration and only the input data changed.
**The second submit does not write the output buffer at all.** A runtime
suspend and resume restores it.

**So only the first submit after a reset computes, and everything after it is a
no-op that leaves the output buffer holding whatever was there before.**

**This retires a whole line of evidence.** Every "re-running the same op is
byte exact" measurement in this file since June fed the SAME input each time, so
a stale buffer and a correct recomputation were indistinguishable. They were
stale. Specifically:

- the 2026-07-26 entry "THE WALL IS NOT POSITIONAL" is **wrong**. It is
  positional. Its evidence was `test_twice.py` with a fixed input;
- "A -> B -> A' gives ok / wrong / ok" is fully explained without any
  configuration story: A computes, B is a no-op so its freshly zeroed buffer
  reads back as the zero point, A' is a no-op so it returns A's old result;
- the scribble result "computes byte exact from a regcmd full of 0xdeadbeef" is
  **wrong**: it does not compute, the buffer is stale. The narrower claim that a
  repeat submit does not re-read its regcmd survives, since it does not read
  anything;
- the 2026-07-25 "one arm per RESET" finding was **right all along**, and the
  90-ops-with-90-resets run agrees: with a reset before every op, every op is a
  first-after-reset and every op computes.

**Igor Paunovic's alternative is refuted, from the same run.** With the watched
BO latched once instead of following each submit, A's buffer is `20a556ae`
before B's submit and `20a556ae` after it. The walled submit does not write the
resident job's addresses either. It writes nothing anywhere.

**Probe bug that made round 6 unreadable**: the stash followed every submit,
so after B the checksum was of B's own buffer, and the "change" from `20a556ae`
to `25c7ae02` was just crc32 of 409600 zero bytes, an untouched BO. Latch the
buffer once. Verified: `python3 -c "import zlib; print(hex(zlib.crc32(b'\0'*409600)))"`.

**What this reframes.** The question is no longer "why does a second
configuration fail to load". It is "why does the block accept exactly one task
per reset". That is a much narrower question, it matches the interrupt
behaviour already recorded here, and it means the mesa side was never the
problem.

## 2026-08-06 (QUALIFIER on the entry below: the no-op reading is UNFALSIFIED, not established. Igor Paunovic named an alternative that fits every measurement, and the probe built to separate them perturbed the system and failed its own control.)

Igor's point, from the v5 thread: marking the failing job's own output BO and
finding it untouched shows the block did not write THERE. It does not show the
block wrote nothing. Everything measured is equally consistent with the block
never having stopped executing the RESIDENT configuration and writing to the
PREVIOUS task's addresses:

- a repeat submit computes byte exact from a regcmd full of 0xdeadbeef, so it is
  demonstrably not fetching;
- the failing job's output is untouched in 100% of the buffer, which is what you
  would see if the write went to the previous task's addresses;
- the resident convolution keeps working across the failure;
- and the one case where corruption does change the result is the first submit
  after a resume, the one submit that follows patch 5's domain reset cycling.

Under that reading the question is not "why does it not start" but "why does the
configuration fetch stop happening after the first post-reset submit".

**A partial counter-argument from data already in hand, with a hole in it.** The
output BO is 409600 bytes = 0x64000, and in both A's and B's `drm_mm` dumps the
only node of that size is at **0xa5000**, so the two address spaces have identical
layouts because the models are structurally identical and each fd gets a fresh
allocator. So A's output iova and B's output iova are numerically the same. B's
domain is attached during B's job, so a write to "A's output address" would land
in B's output BO, which was measured 100% untouched. The hole: rk_iommu has a
TLB, this tree carries a `flush_iotlb_all` patch precisely because invalidation
here has been a problem, and a stale entry could still translate 0xa5000 to A's
physical pages. Not airtight, and it does not remove the need for the direct test.

**The direct test was run and FAILED ITS OWN CONTROL (2026-08-06).** `mark_prev`
filled A's output BO with 0xa5 and `check_watch` reported the surviving fraction:

| step | result |
|---|---|
| 1 invoke A | OK |
| 3 marker in place | 100% (placed correctly) |
| 4 invoke B | WRONG, as always |
| 5 THE QUESTION | 100% |
| 6 invoke A again | **WRONG**, output is all 37 = the marker |
| 7 CONTROL | 100% |

A's own re-invoke did not clear its marker, so the check cannot see writes and
step 5 says nothing. Note step 6: A came back WRONG, and `test_aba` in the SAME
boot had A -> B -> A' with A' fine. **The probe broke A.**

**Probe bug, third distinct kind, do not re-tread.** The first was looking in
the wrong place, the second was a metric that could not fail, this one is
**perturbing the system under test**. `mark_prev` wrote the BO then did
`dma_sync_sgtable_for_device(DMA_TO_DEVICE)`, and `check_watch` read it after
`dma_sync_sgtable_for_cpu(DMA_FROM_DEVICE)` and never returned ownership. That
inserts an unpaired, direction-inconsistent sync sequence into a buffer whose
ownership teflon manages through its own prep_bo/fini_bo ioctls, on a device that
is **not** `dma-coherent` (only the two PCIe nodes are, in rk3576.dtsi). Both
"the NPU did not write" and "the NPU wrote and the CPU read a stale line" fit the
result.

**Replacement, not yet run:** do not write anything. Checksum the resident job's
output BO and watch whether it changes across the walling submit. A(input X) ->
hash, A(input Y) -> hash must differ (that is the control, and it needs no
perturbation), A(input X) -> hash, then B -> hash. A change across B means B wrote
A's buffer. Read-only, ownership returned symmetrically, and A keeps working
throughout.

**Status of the entry below**: the two scribble results stand (a repeat submit
does not re-read its regcmd; the first submit after a resume does). The retraction
of the "zero point surface" reading stands: that buffer is measurably unwritten,
whatever else is true. What is NOT established is that the walled submit does
nothing at all, as opposed to re-running the resident configuration elsewhere.
The v5 cover letter states the stronger claim; it needs correcting in v6.

## 2026-08-05 (SEE THE QUALIFIER ABOVE, the headline claim here is unfalsified, not established. THE WALLED SUBMIT IS A COMPLETE NO-OP. It does not read its regcmd, does not compute, and does not write its output buffer. Both halves have a positive control that passed. Also a RETRACTION: the "zero point surface" we have reported since June was never written at all.)

Igor Paunovic asked on the v4 thread whether the regcmd is read at all on the
submits that fail, and pointed out that everything measured so far is either what
the driver wrote or what the registers hold at completion, neither of which can
separate "fetched and ignored" from "never fetched". He was right that this was
the unexamined half of the path. Four rounds on the board, two of them wasted on
broken probes.

**Round 4, the two results that stand.**

Probe A, `rocket.scribble=N`: overwrite the first N words of the regcmd buffer in
place, just before OP_EN. Finds the BO by walking `priv->mm` (the regcmd BO is NOT
in `job->in_bos`), flushes with `dma_sync_sgtable_for_device` because the NPU is
not `dma-coherent` here, and logs the first word before and after so a write that
did not land is visible as such.

| submit | scribbled | result |
|---|---|---|
| first of the session | yes | **WRONG** (distinct=1, maxdiff=127) |
| a repeat of the same config | yes | **byte exact** |

Same BO, same iova, same 64 words, `first 000e1004 -> deadbeef` confirmed both
times. So a submit that must load does load, and a repeat submit runs from
resident state without re-reading a thing.

Probe B, `rocket.prefill=0xa5`: fill `job->out_bos` with a marker just before
OP_EN. teflon copies the output BO out with a `+0x80` applied
(`rkt_ml_subgraph_read_outputs`), so the marker surfaces in the tensor as **37**
and cannot be confused with the zero point fill.

| submit | marker survives | result |
|---|---|---|
| A, first of the session (control) | **0.0%** | byte exact, maxdiff=1 |
| B, after A is resident (the wall) | **100.0%** | mean 37.0 |

**So the walled submit does nothing at all.** It does not read its configuration,
it does not compute, and it never writes its output buffer, which means it does
not even know where the output goes.

**RETRACTION.** Every report since June, including the v3 and v4 cover letters
on lore, described the walled output as the DPU "writing out a zero point
surface", and read that as the MAC producing nothing. That is wrong. A fresh
shmem BO is zeroed, `0x00` plus teflon's `+0x80` is 128, and 128 is exactly what
we called the zero point fill. The buffer was simply never written. Nothing was
ever measured about the MAC on this path.

Scope: measured for the single-conv A -> B case. The 2026-07-26 entry below, where
`core[dt_wr]` was nonzero on ~56 of 90 ops, is a different regime (a reset before
every op) and is not overwritten by this. But the "it computes zero" reading of
the A -> B wall is retired.

**Probe bugs that cost two board runs. Do not re-tread:**

1. Pointer poison (`rocket.regcmd_probe`): point PC_BASE_ADDRESS at an unmapped
   iova and wait for an rk_iommu fault. No fault on either the walled or the
   working submit, and the poisoned job still computed byte exact. The readback
   added in round 3 explains it: **PC_BASE_ADDRESS reads back 0x00000000 straight
   after the write**. The poison never reached the register, so the probe was
   measuring nothing. Worth knowing on its own: that register is write-only or its
   writes are swallowed.
2. First scribble attempt searched `job->in_bos`. The regcmd BO is not there; it
   is referenced only by iova in the task. Walk `priv->mm` instead.
3. The first wall test compared B's output with and without a corrupted regcmd and
   got "identical". **Void**: B produces a flat constant surface either way, and
   two constant buffers always compare identical. The oracle returned the same
   answer for both of its hypotheses. This is the third time this project has been
   burned by a metric that cannot fail; ask what it reads for a known-wrong input
   BEFORE the flash, not after.
4. `rocket_open()` creates a fresh IOMMU domain and a fresh `drm_mm` per fd, and
   each `load_delegate()` opens its own fd. So two models' regcmd BOs legitimately
   sit at the same iova in different address spaces, and a bare address in a log
   does not identify a buffer. Log `regcmd_count` and the BO size too.

**What this leaves.** The block loads a configuration under some condition, and
when that condition is not met the submit is a no-op that still looks like a
completion, because `INTERRUPT_RAW_STATUS` PC_DONE is permanently latched and the
poll condition is therefore always already true. What that condition is, is the
open question. The ping-pong lead is retired: it was about which bank the
configuration lands in, and the configuration is not being read in the first
place.


## 2026-08-03 (v4 sent: six bugs fixed, none of them the wall. Board-verified before sending.)

`[RFC PATCH v4 0/6]`
<https://lore.kernel.org/all/20260803094125.3285895-1-gahing@gahingwoo.com/>

A fixes only revision. Five of the six came from the Sashiko review bot on v3 and
each was checked against the vendor DT, the vendor driver or the board before
being believed.

| fix | how it was verified |
|---|---|
| `rknn_core_1` was at 0x27710000 | vendor node is `reg = <0x27700000 0x8000>, <0x27708000 0x8000>` and its driver takes `base[i]` from those, so core 1 is at **0x27708000**. `rknn_mmu_1` at 0x2770a000 was right all along |
| both cores had 5 reg entries incl. dpu/dpu_rdma | binding says `maxItems: 3`, and the driver maps three. v3 validated the binding with `dt-doc-validate` but never ran `dtbs_check` on the DTS against it |
| `rknn_core_1` missing the CBUF clocks | the driver asks for six by name on RK3576, so it could never have probed |
| one power domain per core | `dev_pm_domain_attach_list()` returns **-EEXIST** if the driver core already attached a single domain. It only ever worked because rk3576-rock-4d.dts overrode it. Both domains on each core now, board override dropped |
| `rocket_job_fini()` left the poll timer and work running | use-after-free on unbind |
| a queued poll work could finalise the next job | now carries the sequence number of the job it was started for |

**Near miss worth recording:** a blanket replace of the single-domain line also
hit `rknn_mmu_0`, giving the IOMMU two domains. That would stop the driver-core
auto-attach that `rk_iommu` depends on, since it never attaches a list itself, and
the MMU would run on an unpowered domain. Caught by reading the diff before
flashing. The IOMMUs keep one domain each.

Board verification before sending, four parts: the NPU probes with the two-domain
list and no attach failure, `conv2d-cal` stays byte exact 6/6, A -> B -> A is
unchanged (the wall is untouched by any of this), and an unbind/rebind cycle
rebinds cleanly and runs again with no warning or oops.

That last one also reproduced Igor Paunovic's devres leak independently: after
unbind/rebind our `/dev/accel/accel0` comes back as `accel1`. His pending patch 1/2
fixes it.

Igor's `Tested-by` from v3 was not carried over, since patch 4 changed after it.
The cover letter says so and leaves the tag to him.

## 2026-08-04 (Two more clean negatives: the register file is identical between a job that computes and one that does not, and adding the vendor's state_init changes nothing.)

Both of these came out of a list of four ideas, two of which turned out to be
answerable from material already on disk.

**Read snapshot instead of write audit.** Every register comparison in this
project so far has been a writel audit, which by construction cannot see a bit
the hardware sets and the driver never writes. That is exactly the class
`INTERRUPT_MASK` bit 31 belongs to, so it was worth sweeping from the read side.

Snapshot of pc, cna and core (4 KB each, through the driver's own mappings)
taken at the same point in three consecutive jobs of an A -> B -> A run:

```
snap: job0 baseline captured
snap diff pc+0x0008: job0=00000000 job1=00000001
snap: job1 differs from job0 in 1 words
snap diff pc+0x0008: job0=00000000 job2=00000001
snap: job2 differs from job0 in 1 words
```

`pc+0x0008` is `OPERATION_ENABLE`, i.e. the instantaneous OP_EN state at the
moment of sampling. Everything else in 12 KB is identical, and the job that
computed nothing looks the same as the two that computed correctly.

Extended afterwards to DPU and RDMA as well, which rocket does not map: the
vendor DT covers each core as one 32 KB range and its driver reads
0x4000/0x4004/0x4008/0x4018 and 0x5000/0x5004/0x5008, so both blocks are decoded
and safe to read through a separate ioremap. Same answer over all five blocks,
20 KB in total: **one word differs, and it is OPERATION_ENABLE.**

So at completion the hardware presents identical register state whether the job
computed correctly or produced nothing at all. There is no stuck state bit to
find in the register file.

Scope, honestly: sampled at completion, not during execution, and it does not
cover the MMU. A difference confined to the roughly 1 ms the job is actually
running would not show up here, and sampling that window means polling hard
enough to perturb the timing being measured.

A first attempt swept `0x27700000` to `0x27706000` as one contiguous range and
wedged the board with RCU stalls. The culprit is `0x27702000`: mainline splits it
out as `rknn_mmu_0` and `rk_iommu` owns it, so mapping over it is what hung the
bus. DPU and RDMA were innocent and read fine once they got their own ioremap.

Also learned from the vendor DT while checking this: **`rknn_core_1` in our
rk3576.dtsi has the wrong address.** The vendor node is
`reg = <0x27700000 0x8000>, <0x27708000 0x8000>` and its driver takes
`base[i]` straight from those, so core 1 is at **0x27708000**, not the
0x27710000 we wrote. Our `rknn_mmu_1` at 0x2770a000 is 0x27708000 + 0x2000 and
was right all along. The core is `status = "disabled"` so nothing has hit it,
but it needs fixing.

**The vendor's state_init, which rocket has no equivalent of.** `rk3576_state_init`
runs at probe and after every reset and is the only place either driver selects a
ping-pong bank: `S_POINTER 0`, write `DATA_SIZE1`, `S_POINTER 1`, write it again,
arm with `0x1e`. rocket never initialises bank 1 at all, which fit the shape of
the bug well: the first configuration computes and a second, different one does
not.

Added it verbatim, called once per `runtime_resume` exactly where the vendor
calls it (not per job; the old debug tree did it per job, which is a different
thing and also walled). Result: `A ok / B wrong / A' ok`, unchanged in every
respect, with the same-config repeat still 6/6. The story fits the symptoms and
is simply not true.

**Two ideas from the same list closed without a board run:**

- The vendor driver issues no SMC at all. `grep -riE 'smccc|arm_smccc|SMC_|sip|optee'`
  over the whole of `drivers/rknpu` returns one `RKNPU_MEM_SECURE` ioctl flag
  definition and nothing else. The `arm_smccc` calls are in
  `pmdomain/rockchip/pm-domains.c`, which both stacks share.
- `task_pp_en` is already captured and matches. The vendor's real submit records
  `task_con=0x70008`, i.e. `(0x6|pp) << 16 | 8` with `pp = 1`, and rocket writes
  `PC_TASK_CON_TASK_PP_EN(1)`. It also cannot vary per task: it comes from
  `args->flags` and is written into TASK_CON once per submit.

**What is left.** The vendor computes different configurations correctly on this
silicon and this kernel, so a difference exists. It is not in the NPU register
writes (both enumerated), not in the regcmd payload (vendor bytes replayed
through rocket still wall), not in the register state at completion (this entry),
not in clocks, genpd, IOMMU, cache or resets, and not in the ping-pong controls.
The candidates that remain are the CBUF SRAM contents, the DPU and RDMA blocks
that nothing has ever read, and the submit fence timing the dual-image work left
open at low probability.

## 2026-08-03 (Tomeu's ping-pong lead: the pointer IS stuck, but the driver cannot move it. Four ways tried, all null.)

Tomeu Vizoso, on the v3 thread: *"This sounds to me as related to the ping-pong
register mechanism. Your NPU seems to be stuck in the bank 0 and is not
switching to bank 1. This should be done via writes to S_POINTER."*

The register layout supports the idea. `S_POINTER` bit 0 (`POINTER`) selects
the bank; bits 1-3 are `POINTER_PP_EN`, `EXECUTER_PP_EN`, `POINTER_PP_MODE`;
bit 4 is `POINTER_PP_CLEAR`; bit 16 reads back as `EXECUTER`. The vendor's
`rk3576_state_init()` selects a bank with a bare `0` then a bare `1`, writing
`DATA_SIZE1` into each, and finishes with `0x1e`. rocket writes `0xe` both
directly in `hw_submit` and, via mesa, four times inside every regcmd, so bit 0
is always 0 and `POINTER_PP_CLEAR` is never pulsed after power-on.

**The observation is right: the pointer is stuck.** Reading it back:

```
sptr at-kick : cna=0000000f core=0000000f     (we wrote bit 0 = 0)
sptr at-done : cna=0001000f core=0001000f     (EXECUTER latches, stays)
```

We write 0 and it reads 1, on every job, for the rest of the session.

**But the driver cannot move it.** Four attempts, each with the A -> B -> A
oracle (two independently byte-exact models) and a same-config repeat as a
safety net:

| attempt | result |
|---|---|
| flip bit 0 per submit, in the direct writes and in all four regcmd entries | readback unchanged, A ok / B wrong, exactly as baseline |
| bare bank select like `rk3576_state_init` (PP bits cleared) | **units stop arming**: `EXECUTER` never latches and even the normally-good model fails |
| pulse `POINTER_PP_CLEAR` before each submit | pointer does not move, A ok / B wrong |
| pulse `POINTER_PP_CLEAR` + `EXECUTER_PP_CLEAR` | same |

The same-config repeat stayed 6/6 byte exact under the clear pulses, so they
are not breaking anything either. They simply have no effect.

One caveat on reading that table: `post-clear` reading back `0x0f` does not
prove the write was dropped, since `PP_CLEAR` is plausibly a self-clearing
pulse bit. What it does show is that **bit 0 never moved**, which is the thing
being tested.

So the lead is confirmed in its observation and closed in its remedy: the
pointer sits at 1 with `EXECUTER` latched, and `S_POINTER` is not a lever the
driver has. What actually drives it is still unknown.

**What this leaves.** The vendor driver computes multiple different
configurations correctly on this same silicon and the same mainline kernel
(the kiln dual-image result). So it is achievable in software, and something
the vendor does we do not. The old writel audit that found the two byte
identical was taken on what was effectively a first load, before we knew the
failure needs a *second, different* configuration. Re-running that capture
across an A -> B -> A sequence is the obvious next move and has not been done.

## 2026-07-26 (RETRACTED 2026-08-06, SEE THE TOP ENTRY: it IS positional; the evidence below used a fixed input and was reading a stale buffer. THE WALL IS NOT POSITIONAL. The same op re-run six times in one power session is byte-exact every time. What fails is loading a DIFFERENT configuration, not being the second op.)

Every experiment on this wall until now varied two things at once. Chained models
run *different layers*, so "op1 is wrong" could be the position or could be that
layer. `conv2x` cannot arbitrate it either — its op0 is broken too
(`core[dt_wr]=16` where 25600 is due). `conv2d-cal` can: it is byte-exact against
the correct reference, and has been since 2026-06-27.

So run *it* — one known-good conv, six invokes, one interpreter, one delegate, no
teardown and no reset in between, so every invoke after the first is a "later op":

```
invoke 0: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK
invoke 1: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK
invoke 2: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK
invoke 3: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK
invoke 4: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK
invoke 5: distinct=128 mean=145.1 | vs RELU-ref maxdiff=1 exact=100.0%  OK

top[dt_wr=0 dt_rd=6400 wt_rd=3200] core[dt_wr=12800 ...]   (identical each time)
```

**Six for six, no reset needed.** So "only the first op of a power session
computes" is wrong as stated. Re-running the *same configuration* re-arms
perfectly and indefinitely.

What MobileNet's op1 and conv2x's op1 have that invoke 1 does not is a **different
configuration**. The wall restates as:

> Re-running a configuration already loaded is fine. **Loading a new one is what
> fails.** The defect is in the reconfiguration path — the descriptor/weight load
> that must replace an already-resident configuration — not in a start gate that
> only opens once.

This also explains why a mid-session reset restores the read path (interrupts,
per-layer input and weight fetch): the reset clears the resident configuration, so
the next load lands as if it were the first.

It is a different object from everything the ledger has chased under
dispatch/arm/engage, and it points at CBUF/CSC configuration reload.

(Oracle note: the output zero point must come from the model's quantisation
params, not be guessed from the data. A `bincount().argmax()` guess returned 126
instead of 128 on conv2d-cal and made all six invokes read as `maxdiff=2
exact=50.3% WRONG` — a fake result that briefly looked like a third-invoke
degradation.)

**Next discriminator: A → B → A.** Run conv2d-cal, then a different model, then
conv2d-cal again. If the third run also fails, loading a second configuration
poisons the pipeline for everything. If it recovers, only the new configuration
fails to land and the old one is still resident — which would put the defect
squarely in the weight/descriptor load itself.

**First attempt at that was invalid, and the control is why.** With B=`dwconv` it
gave a clean-looking `A ok / B all-zero / A' ok`, read as "only the incoming
config fails to land". Then the control — run dwconv *first*, as the only config
in a fresh session — returned `distinct=2 maxdiff=248 exact=0.5%`. dwconv is
simply broken on its own, so B failing said nothing about second loads. Any A/B
experiment here needs a B that is independently known good.

**Model catalogue (each measured as the FIRST config of its own power session,
with a sleep between models so the NPU autosuspends in between):**

| model | standalone verdict |
|---|---|
| `conv2d-cal` | **OK** — `maxdiff=1 exact=100.0%` |
| `conv2d` | **OK** — `maxdiff=0 exact=100.0%` |
| `conv2x` | WRONG — all zeros |
| `dwconv` | WRONG — `distinct=2`, essentially all zeros |
| `md003` | WRONG — `distinct=1`, all zero-point |
| `add` | not delegated (no NPU output line) |
| `md011` | segfaults |

Two independently-good models is the minimum needed to run the A/B experiment at
all, and until this sweep there was only one. Also settles two things that had
been assumed rather than measured: `conv2x`'s op0 is broken **standalone**, so its
failure is its own bug and not the wall (an earlier note calling it "known good"
was wrong); and `conv2d` is usable as an oracle after all — the old warning about
it applied to `distinct` as a proxy, not to maxdiff against the relu reference,
where it scores exactly 0.

`dwconv` being broken standalone is worth its own line: MobileNet is mostly
depthwise layers, so some part of "op1+ produce nothing" may be this separate
depthwise bug rather than the wall.

## 2026-07-26 (RETRACTION: the "NPU power domain cannot reach idle" hazard reported below was a SERIAL CONSOLE PRINTK FLOOD, not a power bug. Plus: the wall itself re-measured on a quiet console and is unchanged.)

**Retract this, from the entry below:**

> After 90 mid-session resets the NPU power domain could not be shut down, and
> it took the system with it [...] Something is left outstanding on the NPU's
> AXI/BIU by the repeated resets, `nputop` never reaches idle [...]

Wrong. It reproduces with **zero** mid-session resets, on a single-op model,
with the whole interrupt probe disabled. What actually caused it: the test
script ran `dmesg -n 8`, so every kernel message went to the 115200 serial
console, and the debug kernel emits several hundred `CNAREG` lines per job.
That is seconds of interrupt-blocking output per op. The symptom list was the
signature of exactly that, and it was misread as an NPU power problem:

```
dwmmc_rockchip: Unexpected interrupt latency      <- classic long-printk symptom
cpu4: _set_opp_voltage: failed to set voltage: -110   <- ETIMEDOUT on the PMIC I2C
rcu: INFO: rcu_preempt detected stalls on CPUs/tasks
rockchip-pm-domain: failed to set idle on domain 'nputop', val=0
```

Setting `dmesg -n 4` (console gets warnings only; the ring buffer, which every
summary actually reads, is untouched) makes it go away completely: all four
domains power down cleanly, both models run to completion, and Python's stdout
— which had been queued behind the same serial port — appears again. Three
successive attributions for this were wrong before that one (the resets, then
the vendor-style ack not writing INTERRUPT_MASK=0, then the runtime_suspend
quiesce added to fix it); none of them was the cause.

**The wall itself is NOT a console artifact.** Re-measured with the probe off
and the console quiet, MobileNet reproduces byte for byte:

```
op0   top[dt_rd=9408 wt_rd=96]  core[dt_wr=25088]  out distinct=238  (real)
op1+  top[dt_rd=0    wt_rd=0 ]                     out distinct=1
```

`conv2d-cal` also still passes against the correct reference — the hardware
applies a ReLU at the zero point, so `max(CPU, zp)` is the reference, not raw
CPU: `vs RELU-ref maxdiff=1 mean|diff|=0.00 exact=100.0%`.

**Counting results re-measured on a quiet console — mostly hold, one does not.**
Per-op resets still break the interrupt lockout (63 interrupts in one power
session against exactly 1 without resets), and the per-layer fetch depth still
returns in full (`wt_rd` 512…65536, `dt_rd` 1568…25088). But the **"one
interrupt per reset" 1:1 does not survive**: 90 resets yielded 63 interrupts.
The earlier 64/64 was measured with the reset cap set to 64, so both counters
hit the same ceiling and the 1:1 was partly an artifact of the cap.

**New minimal repro: `conv2x.tflite`** (40x40x16, two chained convs). Its
*first* conv already fails — `core[dt_wr]=16` where 25600 is expected, output
all zeros — and test_conv.py classifies the failure as `PER-CHANNEL (A/bias/C
coef -- DERIVABLE)`, which points straight at the requant coefficient work.
Two ops instead of ninety, and op0 broken rather than op0 good, makes this a far
better place to work than MobileNet.

## 2026-07-26 (CORRECTION to the entry below, and a sharper localisation: with a reset before every op the ENTIRE data path works — interrupts, per-layer input fetch, per-layer weight fetch, and DPU write-back. What is still dead is the multiply-accumulate itself.)

**Correction first.** The entry below concluded "`top[dt_wr]` stays 0 throughout, so
by this ledger's own oracle the write-back is still gated". That inference is wrong.
`top[dt_wr]` reads 0 for **op0 as well**, and op0 demonstrably produces a real output
(`distinct=239`). The write counter is `core[dt_wr]`, not `top[dt_wr]`. Everything
else in that entry stands; this one deduction does not.

**Round 11: 90 ops, 90 mid-session resets, 87 completion interrupts, one power
session.** With the reset cap raised past the op count and the per-BO dump limit
lifted (it was hard-coded to the first 8 jobs, which is why round 10 could not read
the interesting ops), `core[dt_wr]` is nonzero for roughly 56 of the 90 ops:

```
core[dt_wr=6272 ] x19   core[dt_wr=25088] x16   core[dt_wr=3136] x10
core[dt_wr=9408 ] x5    core[dt_wr=4928 ] x5    core[dt_wr=12544] x5
core[dt_wr=16112] x1    core[dt_wr=0    ] x34
```

**The DPU writes.** And the fetches are no longer "warming up" — they are the real
per-layer shapes of the graph:

```
wt_rd in {96, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}
dt_rd in {1568, 3136, 4704, 6272, 9408, 12544, 25088}
```

**But what lands is empty.** Output buffers across the run:

```
distinct=1  x17    distinct=2 x6    distinct=3 x4
distinct=10 x4     first=1d 80 80 80 80 df 80 80   (zero-point dominated)
distinct=239 x3    all iova=0xfeb2d000 with identical bytes -- op0's own buffer
                   being re-read as a later layer's input, not a new result
```

**So the wall localises much more sharply than "the pipeline does not re-arm".**
With a per-op reset the arm works, the input DMA works, the weight DMA works, and
the DPU write-back works — every stage moves the right number of bytes for its
layer. The multiply-accumulate is what produces nothing: the DPU faithfully writes
out a zero-point surface. This lines up with the long-standing "empty conv, MAC≈0"
reading in the payload-replay work rather than with any arm/dispatch theory.

**Per-op reset is not a usable workaround.** After 90 mid-session resets the NPU
power domain could not be shut down, and it took the system with it:

```
21.58  npu0 -> OFF
25.91  rockchip-pm-domain: failed to set idle on domain 'nputop', val=0
26.75  cpu4: _set_opp_voltage: failed to set voltage (712500 ...): -110
       cpufreq: __target_index: Failed to change cpu frequency: -110
42.52  rcu: INFO: rcu_preempt detected stalls on CPUs/tasks  -> CPU0 wedged
```

Something is left outstanding on the NPU's AXI/BIU by the repeated resets, `nputop`
never reaches idle, and the failure propagates into the shared regulator/I2C path
(-110 = ETIMEDOUT), then cpufreq, then an RCU stall. The inference itself had
already completed; this is a teardown hazard, not a data failure. Any future use of
mid-session resets needs a drain/quiesce before power-off.

## 2026-07-25 (DECISIVE: the "one op per power session" wall is NOT per-power-session. A mid-session NPU reset re-arms it — 64 times in one power session, 64 completion interrupts, and the input+weight fetch comes back. Only the write-back never returns.)

Follow-on to the bit-31 entry below. Rounds 8-10 of the interrupt probe, on a
single power session (`npu -> ON` at 19.13, `-> OFF` at 21.84 — no power cycle
anywhere in between).

**Method that finally worked.** Do not reset inline in `rocket_job_hw_submit()` —
this driver already documents why in `rocket_device_runtime_resume()`: the reset
disturbs the MMU banks, so it must land on an *unattached* IOMMU. Instead request
the driver's own recovery path (`reset.pending = 1` + `queue_work(core->reset.wq,
&core->reset.work)`), which does `drm_sched_stop` → detach iommu →
`rocket_core_reset` → `drm_sched_start`, and let the next job re-attach on a clean
MMU. Clean every time: `RDERR=0`, no freeze.

**Result 1 — the interrupt lockout is fully and repeatably breakable.**

```
reset #1  irqs=1/0      reset #2  irqs=2/0   ...   reset #64  irqs=64/0
```

64 resets, 64 GIC completion interrupts, one power session. Every previous run in
this investigation got exactly one interrupt per session. It was never a
per-session limit; it was one arm per *reset*, and the only reset was the one
`runtime_resume()` does at power-up.

**Result 2 — the fetch path comes back with it, and deepens.** Ops that directly
follow a reset (`b31=clear`) fetch; ops that do not (`b31=SET`) fetch nothing.
64 samples, strict correspondence:

```
op63  (after reset)  top[dt_wr=0 dt_rd=12544 wt_rd=512]
op64  (after reset)  top[dt_wr=0 dt_rd=25088 wt_rd=1024]
op65  (cap hit)      top[dt_wr=0 dt_rd=0     wt_rd=0]
op66  (cap hit)      top[dt_wr=0 dt_rd=0     wt_rd=0]
```

`wt_rd > 0` is new: in every earlier run the ops after op0 fetched **no weights at
all**. And the depth grows across successive resets — op1 `dt_rd=5152 wt_rd=0`,
op63 `12544/512`, op64 `25088/1024` — as if the pipeline warms back up rather than
snapping back. The counter is genuinely per-op, not cumulative: op65 onward read
exactly 0, which a stale counter could not do.

**Result 3 — the write-back never returns.** `top[dt_wr] = 0` throughout. By this
ledger's own oracle (`dt_wr == 0` with `dt_rd`/`wt_rd` > 0 = "reads input+weights
but never writes — a compute/config gate"), the MAC result still does not land.

**So the wall's shape changes.** It is not "the CBUF→CSC→CMAC arm only fires once
per power session". It is: **a reset re-arms the read side of the pipeline —
interrupts, input fetch, and then weight fetch — and something on the write side
stays gated regardless.** Power cycling only ever appeared to be the cure because
it contains a reset.

**Two honest limits on Result 3.** The per-BO output dump is capped to the first
few jobs, so op63/op64's buffers were not read directly — "no output" rests on the
`dt_wr` oracle, not on a byte comparison. And the `exec: ever_bit16` readings
contradicted themselves this round (0 for the ops that fetched, 1 for the ops that
did not); they are single-sample snapshots and nothing above leans on them. The
next run raises the reset cap to cover every op and re-enables the output dump for
late ops, to replace the indirect read with a direct one.

**Probe bugs found along the way — recorded so nobody re-treads them as data.**
Four runs looked like results and were not: (1) a one-shot ladder fired before op0
because bit 31 is already set at boot, burning its only run before the lockout it
was meant to break; (2) the every-submit step was logged behind an `op_index < 8`
gate while the op index is module-lifetime, so it ran silently for two whole runs;
(3) an inline reset over a live IOMMU attachment produced `RDERR=1` and confounded
"compute did not come back" with "we broke the mappings"; (4) requesting a reset
means bailing out of the submit, so the scheduler retried the same job, which
requested another reset — 64 resets in 150 ms with not one op in between. Fixed by
gating on the *submit* counter, which only advances for jobs that reach hardware.

## 2026-07-25 (THE WALL NOW HAS A REGISTER ADDRESS: PC INTERRUPT_MASK bit 31 is a session-scoped hardware state that gates the completion interrupt AND the compute, together, and only a genpd power cycle clears it. Five board runs.)

Prompted by Alexey Charkov's review of RFC v2 on lore: *"This whole polled-interrupt
part looks very suspicious. Does the vendor stack do the same thing? ... one theory
could be that the interrupt bits are not read-only per se, but rather gated inactive
by some internal hardware state which must be cleared before jobs are submitted ...
If so, this same hardware state may well be the cause of your observed 'first
(forced) job completes, others don't'."* He was right, and the probe found the state.

**First, the fact that answers his question:** the vendor rknpu driver is fully
interrupt-driven on RK3576. `rk3576_npu_irqs[] = { "npu0_irq", "npu1_irq" }`
(rknpu_drv.c:129), `devm_request_irq()` + `wait_event_timeout(job_done_wq)`, on
`GIC_SPI 247/248` — **the same lines rocket uses**. It does not poll.

**What five board runs established (all reproducible, three independent power
sessions in one boot):**

| | first op of a power session | every op after it |
|---|---|---|
| GIC interrupt | fires once, `raw=0x30000155` | never fires again |
| INTERRUPT_MASK bit 31 | clear | **SET** |
| `top[dt_rd / wt_rd]` | 9408 / 96 | **0 / 0** |
| output | REAL (`nz=4094/4096 distinct=239`) | empty |

`0x155` decodes as `DPU_0 | CORE_0 | CNA_CSC_0 | CNA_WEIGHT_0 | CNA_FEATURE_0` —
the whole group-0 pipeline reporting done, i.e. exactly the completion the vendor
arms with `int_mask = 0x300`. So the interrupt path works; we get precisely one
per power session, on the one op that does real work.

**Bit 31 is set by hardware, not by us.** The armdbg PC dump reads `20=0x80000300`
*before* our handler had run, and it survives the handler writing
`INTERRUPT_MASK=0x0` (the dump then reads `20=0x80000000`).

**Within a power session, no software write clears it.** Swept as a ladder and then
as composite steps applied on every submit, at two different insertion points
(before the mask arm, and after the INTERRUPT_CLEAR write — the last interrupt
register write before OP_EN):

| write | result |
|---|---|
| `INTERRUPT_CLEAR = 0x1ffff` (the vendor's own `RKNPU_INT_CLEAR`) | bit 31 still set |
| `INTERRUPT_CLEAR = 0x80000000` | still set |
| `INTERRUPT_CLEAR = 0xffffffff` | still set |
| `INTERRUPT_MASK = 0x80000000` | still set |
| `INTERRUPT_MASK = 0 → 0x300` | still set |
| all six in the round-2 order, every submit | still set |
| **genpd power-off → power-on** | **clear** |

(One false positive to not re-tread: an early one-shot ladder DID report CLEARED.
It ran *before* the session's single interrupt — bit 31 is clearable up to the
first interrupt and unclearable after. The one-shot also burned its only run
before op0, and its every-submit successor was logged behind an `op_index < 8`
gate while the op index is module-lifetime, so two intermediate runs looked like
data and were not. Sampling at OP_EN (`at-kick`) is the only reading that counts.)

**Second, independent result: `INTERRUPT_RAW_STATUS` bits 28-29 (PC_DONE) are
permanently latched.** `raw 30000000->30000000` even after writing `0xffffffff` to
INTERRUPT_CLEAR. They are high at *every* submit, including the first. So rocket's
hrtimer completion poll — which waits for exactly those bits — has a condition that
is already true before the hardware has done anything. **The completion poll is not
a completion oracle.** It has never been one.

**What this changes.** The wall's description tightens from a behavioural inference
("the CBUF→CSC→CMAC cold-start consume-arm only fires once per power session") to
something with an address: **there is a session-scoped hardware state, visible as PC
`INTERRUPT_MASK` bit 31, which gates interrupt generation and CMAC compute together,
and which only the NPU power domain cycling resets.** This is also why a year of
writel-auditing could not see it: that audit diffs *writes*, and this is a
hardware-set bit that only differs on *readback*.

Bit 31 is a thermometer, not a lever — it cannot be pulled. But it is now a
one-line oracle: any future "did this re-arm the pipeline?" question can be answered
by reading it, instead of running a full inference and classifying the output.

**Consequences for the RFC (independent of anything above):** the v2 patch 6 comment
claiming PC_DONE "is read-only in INTERRUPT_MASK, so it cannot be routed to the GIC"
is wrong about completion in general — `0x300` is writable, sticks, and the line
fires. That justification must be corrected in v3, and the completion detection
itself reworked since the bits it polls are permanently latched. Also to fix in v3:
the sent v2 `hw_submit` arms a DMA-error-only mask while the tree we actually test
arms the vendor's `0x300`, so a reviewer reproducing from v2 would not see what we
see. Probe lives behind `rocket.intprobe` / `int_vendor_ack` / `int_b31_*`.

## 2026-07-25 (RETRACTION + CLOSED LEAD: the "NPU1 power-domain is the root cause" entry that stood here was WRONG. Do not re-tread it.)

An entry posted here earlier today claimed the task2+ wall was caused by NPU1 never being powered, and claimed a fix had been applied to the base `rk3576.dtsi`. Three checks kill it:

1. **It was already done, a month earlier.** `kernel/0015-accel-rocket-rk3576-attach-both-NPU-power-domains-PD.patch` (2026-06-19) puts `power-domains = <&power RK3576_PD_NPU0>, <&power RK3576_PD_NPU1>;` on `rknn_core_0` in `rk3576-rock-4d.dts` **and** adds the explicit `devm_pm_domain_attach_list()` in `rocket_core.c` (needed because a multi-PD device skips the driver-core single-PD auto-attach). Both are live in the build tree (`rk3576-rock-4d.dts:881`, `rocket_core.c:139`) and shipped in RFC v2 patch 8/8.
2. **The board we test on is a ROCK 4D**, i.e. the board that has both domains. Every experiment since 2026-06-19 — the ordered writel-trace, the forced 594 MHz clk run, vendor two-submit, spread-confirm, the CM5 corroboration — ran with NPU0 *and* NPU1 attached. The wall never moved. "All boards except rock-4d only power NPU0" cannot explain a failure on rock-4d.
3. **This ledger already recorded it as a hardware negative**, in the "Ruled out" table below: `dual power domain (PD_NPU0 + PD_NPU1) | added multi-PD attach (dev_pm_domain_attach_list) — no change`.

The claimed "FIX APPLIED / rebuild in progress" also never happened: `rk3576.dtsi:1880` is still `<&power RK3576_PD_NPU0>` and the kernel tree is clean.

What is true and worth keeping: Olaf001au's genpd/OPP dump in [issue #2](https://github.com/gahingwoo/linux-rk3576-npu/issues/2) (2026-07-23) shows the vendor arming `npu`/`nputop`/`npu0`/`npu1` together on every submit, and he fairly asked whether rocket does the same. Answer: yes, and has since 2026-06-19. So genpd hierarchy joins registers and clock rates as **matched-and-still-walls** — the difference sits below all three, at the per-task sequencer arm. (Whether the *base* `rk3576.dtsi` should also list NPU1 on `rknn_core_0` is a separate upstream question — architecturally core0 is PD_NPU0 and core1 is PD_NPU1 — and is unrelated to the wall.)

## 2026-07-17 (DISCRIMINATOR: vendor rknpu on the MAINLINE-7.1.3 kiln image explicitly COMPUTES a real 53-layer MobileNetV2 correctly. This makes the long-implicit "vendor-on-mainline works" datapoint explicit — and, on checking the Kiln ledger, it does NOT create tension with the RTL verdict: that verdict was reached WITH this exact fact as its premise. Prompted by issue #2 (Olaf), whose CBUF-clock lead is largely covered by the existing clk env diff.)

Ran the Kiln image (mainline-7.1.3 kernel + out-of-tree vendor `rknpu.ko` 0.9.8 autoloaded + real `librknnrt.so`) with an added auto-verdict init. Result: `rknn_mobilenet mobilenetv2-12_rk3576.rknn test.jpg` → top-1 `[494] chime, bell, gong` (logit 18.67, clean margin over #2 milk-can 12.04), 5.9 ms. `test.jpg` is a bell (Kiln `docs/VISION.md`), so the classification is CORRECT. The driver logged its clock at init: `kiln clk: dsu0=594000000 aclk0=594000000 aclk1=594000000` (594 MHz = GPLL/2, the CRU default). (Self-note: my auto-threshold fired on the raw logit, not a softmax prob — the verdict was right but for a naive reason; the real oracle is that the class is a bell.)

**This is the KNOWN Kiln baseline, not a new result.** Kiln's whole purpose is vendor-rknpu-on-mainline, and its memory already records this working (`kiln-blindspot-grf-repair-refuted`, `kiln-rocket-wall-doubly-closed`). What it adds HERE is making the datapoint explicit in this ledger and closing a question this repo had left ambiguous: *was the vendor driver ever confirmed to COMPUTE task2+ on mainline, or only register-diffed?* Answer: it computes, cleanly.

**The apparent tension with the RTL verdict — and why it dissolves.** On first read this looks like it reopens the software path: vendor computes, rocket walls, SAME mainline kernel, and the dual-image already proved their register writes byte-identical → so the difference must be a non-register SOFTWARE behavior (clock/mapping/timing), i.e. NOT RTL. But that is exactly the reasoning the Kiln ledger already ran to completion: the plan `wall = rocket DRIVER task_number=N environment → next = same-kernel vendor-vs-rocket ENV diff` IS the dual-image, and its env diff (ftrace `regmap` over genpd/**clk**/QoS/vdd, plus per-driver wtrace of every readl/writel) came back identical except non-NPU housekeeping. The RTL verdict is "vendor computes and rocket walls on one kernel with identical register AND env writes" — it presumes vendor-on-mainline works; that fact is its foundation, not its counterexample. So: no reopening. The discriminator confirms the premise, it does not break the conclusion.

**Olaf's CBUF-clock lead, against this:** the Kiln node takes all 5–7 DT clocks incl. `ACLK_RKNN_CBUF`/`HCLK_RKNN_CBUF` via `devm_clk_bulk_get_all`, and runs `DSU0` at the CRU default (594), the same as rocket (which "sets NO assigned-clocks/rate and computes at the CRU default"). The clk env was in the dual-image diff and matched. So the lead is largely covered. The one thin residual: that diff captured regmap *writes*, not the resulting clk-tree *rates* (`clk_summary`). Reading the actual NPU clk-tree rates on both the vendor and rocket boots of the same kernel would close even that — cheap, and it's the concrete artifact Olaf asked for.

**RESOLVED (same-kernel clk-tree diff + forced-match test, 2026-07-17).** Read the actual rates. There IS a real difference on the same mainline kernel:

| clock | vendor (kiln, `clk_summary`) | rocket (`rocket dbg clk`) |
|---|---|---|
| dsu0 / npu (compute) | 594 MHz | 786 MHz |
| aclk_rknn0/1 (AXI) | 594 MHz | 786 MHz |
| **aclk_cbuf** | **594 MHz** | **786 MHz** |
| hclk_root / hclk_cbuf | 198 MHz | 198 MHz |

So Olaf's instinct caught a genuine difference: rocket runs the NPU compute+CBUF AXI domain at 786, the working vendor at 594 (hclk domain matches). Forced rocket to the vendor's EXACT rate via the `npu_clk_hz`/`aclk_hz`/`cbuf_clk_hz` params (runtime, no rebuild) — confirmed it took: `rocket dbg clk: aclk=594000000 npu=594000000 aclk_cbuf=594000000 hclk_cbuf=198000000`, byte-identical to the vendor clk tree — and re-ran multi-task. **Result: wall unchanged. op0 output buf distinct=232 (REAL), op2+ output bufs nz=0/4096 distinct=1 (EMPTY).** So the CBUF/compute clock RATE is NOT the wall — matching it exactly changes nothing. This CLOSES Olaf's CBUF-clock lead with hard same-kernel data (measured, not "thematically weakened"), and is consistent with the vendor computing at BOTH 198 (Olaf's 6.1.115 BSP) and 594 (mainline) — two very different cbuf rates that both compute. Net: on one mainline kernel, vendor computes / rocket walls with register writes (dual-image) AND clk-tree rates (this) now both matched → the difference is below both. Back to the sequencer tier.

## 2026-07-17 (INDEPENDENT CORROBORATION on a SECOND board (ArmSoM CM5) + a THIRD method (ftrace ioctl call-graph on the live production vendor stack). The whole 53-layer graph executes inside ONE blocking submit_ioctl with no per-layer ioctl or kernel register write — the per-layer CMAC engage is entirely hardware-autonomous, invisible above the register interface. Kernel/MMIO tracing is now closed from two environments and three methods.)

Fresh test on ArmSoM CM5 (RK3576 — SAME SoC as the ROCK 4D, so this is on-SoC corroboration, not cross-SoC), genuine unmodified vendor BSP (6.1.115-vendor-rk35xx, RKNPU 0.9.8) + genuine closed userspace runtime — a different board and a different method from this repo's mainline-7.1.3 dual-image rig. Directly establishes that the same RK3576 vendor silicon runs 53-layer chained inference correctly, so the chained-CMAC wall is a rocket/open-stack limitation, not an RK3576-hardware one.

- **Vendor chained inference works end-to-end, one power session, no power-cycling:** MobileNetV2 (53 conv layers) via librknnrt.so classifies real photos correctly (cat→tiger cat 20.9%/tabby/Egyptian; dog→Shih-Tzu 55.9%/Pekinese/Lhasa); Llama-3.2-1B via librkllmrt.so (hundreds of chained transformer matmuls) generates coherent tokens across a full session. The real reference, working.
- **ftrace of the ioctl call-graph during a live 53-layer MobileNetV2 inference:** `__rknpu_action_ioctl` ×12 (all <50us — version/capability/task-number queries), then a SINGLE `__rknpu_submit_ioctl → rknpu_submit_ioctl → rknpu_job_schedule/rknpu_job_next` that BLOCKS for ~13243.87us — **the entire 53-layer graph executes inside that one call**. No per-layer ioctl, no per-layer kernel-side register write in the call set. The per-layer CMAC engage transition happens entirely inside one hardware-autonomous blocking window.
- **Corroborates the dual-image / CHAINED-CMAC-STOPPING-POINT closure from a new angle** (ioctl-call layer on the real vendor stack, vs the whole-address-space writel/readl diff). Same conclusion, independent method + board.
- **One box left unverified (flagged, not silently assumed identical):** the 12 `__rknpu_action_ioctl` argument/cmd payloads were not decoded (needs kprobe arg-capture or a debug-symbol build; strace absent on the board). Any of these translating into an MMIO write would have been caught by the existing writel/readl diff, so new signal is very unlikely — but it is the one thing not directly checked.

**VERDICT: NO-GO on kernel/MMIO/ioctl tracing as a path forward** — closed by this repo's ledger and independently re-closed today at the ioctl-call layer on a second board. The only tier that could extract the chained-CMAC state is TRM/RTL or silicon-level debug (JTAG), exactly what the ledger already identified. Nothing in today's probing reopens the software path; it narrows it further.

## 2026-07-17 (ORDERED WRITEL-TRACE, ROCKET vs VENDOR, apples-to-apples — answers "any notable timing/order difference?" NO. rocket's dead op1 kick is byte-identical to its own working op0 kick; the only diff vs the vendor is rocket writes EXTRA unit-enable pulses. No observable-write difference distinguishes the computing submit from the empty one.)

Captured rocket's per-submit register writes with timestamps (rocket `wtrace`, "rocket wt <seq> <off> <val> <caller>", identical format to the vendor's `rknpu wt`) and lined them up against the vendor trace (2026-07-16). Ran rocket in the VENDOR-matching regime: `perjob_ppinit=0` (so `rocket_core_pp_state_init` runs once at cold/resume, not per job — the vendor arms once), power pinned (`autosuspend_delay_ms=3600000`, one session), MobileNet + `ROCKET_TILE_JOBS=1`.

- **pp/state-init cadence now matches:** rocket `pp_state_init` = 1 block (6 writes) at cold, then per-op kicks only — same as the vendor's single `rk3576_state_init`. (Default `perjob_ppinit=1` re-runs it per job, 12x for conv2x — rocket does MORE than the vendor, not less; setting =0 removes that difference.)
- **op0 REAL, op1+ EMPTY:** op0 `out_class=REAL distinct=256 nz=400932/802816`; op1/op2/op3 `EMPTY nz=0`.
- **op0 kick == op1 kick (order + values):** `0x0010=1, 0x1004=0xe, 0x3004=0xe, 0x0010=<regcmd>, 0x0014=<amount>, 0x0020=0x300, 0x0024=0x30000300, 0x0030=0x00070001, 0x0034=0, 0x2210=0x80000101, 0x2210=0x00000101, 0x2410=0x80000101, 0x2410=0x00000101, 0x0008=1, 0x0008=0`. The dead op1 kick differs from the computing op0 kick ONLY in the regcmd address and the `0x0014` data-size (different layer). Same registers, same order, same timing shape.
- **Only structural diff vs the vendor:** rocket's kick writes two extra unit-enable pulses (`0x2210`/`0x2410` = 0x80000101→0x00000101) that the vendor's kick never issues — the vendor's units engage from the S_POINTER arming (`0x1004/0x3004=0xe`) alone (the "4 extra" from the 2026-06-30 WRITEL AUDIT). rocket NEEDS them (drop the enables and units don't engage even on op0, per 2026-06-30) yet WITH them op1 still does no MAC. So rocket does an EXTRA engage step, not a missing one. rocket also folds the int-mask as one write (`0x0024=0x30000300`) vs the vendor's split (`0x300` in-kick + `0x30000000` post-completion) — same bits.
- **Timing:** conv exec is a few ms both sides (vendor OP_EN→IRQ ~2ms); warm-op cadence ~40-50ms both, dominated by driver/userspace overhead, not compute. No "vendor waits at a magic moment" step.

**VERDICT: no observable timing/order difference explains it.** Within rocket, the computing op0 and the empty op1 issue byte-identical, same-order, same-timing kicks; the only thing rocket does that the vendor doesn't is ADD unit-enable pulses. The 2nd-MAC failure is below the observable write sequence — consistent with the CSC/CMAC-sequencer verdict. (Trace facility: rocket `wtrace` param; helper `vendor-capture/split_wt.py`.)

## 2026-07-16 (VENDOR TWO-SUBMIT CONTROL + PINNED-SPREAD — falsifies the "locked state is normal, the blob recovers from it" proposal (alchark). The working vendor stack NEVER enters the wall on a 2nd submit in one power session; the warm re-arm is not a register write and not a power/reset teardown — it is below the register interface. Fifth independent line converging on the RTL/sequencer verdict.)

The literal proposal (run the blob right after a rocket submit, same boot, no powerdown) is not doable: rocket and the vendor rknpu can't both bind `npu@27700000` (one DTB/boot), and the handoff forces a genpd power-cycle + the vendor's `state_init` re-arm, so the blob would run on a fresh core. So the underlying question — does the WORKING vendor stack ever wall on a 2nd submit in one power session — was tested three ways.

- **Vendor, 5 back-to-back independent submits in ONE power session** (`runner_multi` + `exp2` calibrated non-saturating conv; gaps 45ms << the 3s autosuspend, so no powerdown): all 5 outputs byte-identical (`md5 659251174b58bb655bd0ac310f008e7f`) and match the rknn simulator golden (`min -1.559e6 max 1.321e6`). **The vendor re-arms on every submit — it never enters the wall.** So the locked state is NOT normal HW behaviour; it is rocket-specific.
- **Ordered writel trace of the vendor driver** (`rknpu wtrace`, `split_wt.py`): the warm-submit register kick is BYTE-IDENTICAL to the cold one (`0x1004=0xe, 0x3004=0xe, 0x0010=regcmd, 0x0014=0x47, 0x0020/0x0024=0x300, 0x0030=0x00070001, 0x0034=0, 0x0008=1`). Between submits the vendor does NOTHING — no reset, no CBUF reinit, no IOMMU touch; just the IRQ int-clear (`0x0024=0x0001ffff`) + a ping-pong S_POINTER re-arm. No "detect + recover" step: the cold-start `state_init` latch (`0x10=1`; `0x1004` 0→1→0x1e; `0x1024=0x80000000` ×2) persists for the whole power session.
- **Rocket, power pinned to one session** (`S98mndump-pinned`, `autosuspend_delay_ms=3600000` on `27700000.npu`): removes the genpd power-off between per-op submits, so no reset / `pp_state_init` / IOMMU teardown — exactly the vendor's regime. **ops 1+ still come out all-zero** (361 spread lines: op0 REAL, ops 1..360 `out_class=EMPTY nz=0`). `core_dt_wr=25088` is constant across ops of output size 4096..1048576, i.e. the dirty-counter artifact, not real MACs.

**VERDICT: the missing warm re-arm is silicon-level — below the register interface (the CSC/CMAC sequencer) — not a normal/recoverable state and not a power/reset teardown.** The blob never gets into the wall; rocket can't be coaxed out of it by removing the teardown. Fifth independent line (after WRITEL AUDIT, the ordered trace, the dual-image replay `FINDINGS-DUAL-IMAGE.md`, and the from-scratch re-audit 2026-07-10) landing on the same RTL verdict. Lead closed.

## 2026-07-10 (INDEPENDENT RE-AUDIT + CONSOLIDATION — a from-scratch, source-only
audit (no findings docs read first) covering the rocket kernel driver, the vendor
rknpu kernel driver, and the mesa regcmd/task-chain builder independently converged
on the same wall this file already closed, and one of its two leading candidates was
found to duplicate a change already tried and reverted here. Kernel patch 0028
consolidates the settled Phase A/B dispatch (TASK_CON.task_number=job->task_count,
one PC_OP_EN pulse, mesa-packed contiguous task regcmds) into the driver's
unconditional default and removes the now-dead experimental module_param forks
(chain_task_number, wg_continuous flag, bare_tasknum, wg_warm_chain, bisect,
rekick_reset, audit_all, pw_weight_sram, geom_all, conv0_twice, open_high, pp_alt,
trailer_check, zero_out_bos, spread_confirm, read_margin, cbuf_reset variants) that
enumerated the now-concluded alternatives.)

The audit's first candidate — build a vendor-style flat task-descriptor array +
`TASK_DMA_BASE_ADDR` pointing at it + `TASK_CON.task_number=N` together, on the
theory that no prior experiment had varied `task_number` and the array pointer
*together* — is refuted by this file's own WRITEL AUDIT entry (2026-07-04, below):
a live capture of the vendor's own submit shows `task_base_addr=0` even at
`task_number=2`, i.e. the vendor was captured *not* using the descriptor-array
mechanism either. So the untested combination doesn't exist to test: the vendor
grammar is the contiguous-stream self-iteration trailer (WHOLEGRAPH-GRAMMAR.md), not
an array walk, and that grammar was already implemented, board-tested, and hit the
same wall (Phase B, 2026-07-05 below).

The audit's second candidate — a CBUF/executer "arming state does not survive
task-to-task" gap — is not new: it is this file's own SPREAD-CONFIRM /
cold-start-is-per-power-session verdict (2026-07-05, below), independently
re-derived from a blind source read rather than assumed. No new candidate survived
the fresh pass. This is the second, independent line (the other being the same-
kernel vendor-vs-rocket dual-image cross-check, `FINDINGS-DUAL-IMAGE.md`) to close
on the identical RTL/internal-sequencer verdict — cross-validation across dispatch-
mechanism, cache/TLB/register-value, and now a from-scratch full-stack re-derivation.
Nothing further is actionable from software alone without vendor RTL/TRM access.

## 2026-07-05 (SPREAD-CONFIRM — the per-op-dispatch ESCAPE HATCH is CLOSED. N genuinely-independent single-task submits do NOT re-arm the CSC: only op0 (the first job after each NPU resume) computes REAL; every subsequent independent submit is EMPTY. Cold-start is PER-POWER-SESSION, not per-submit. The SPREAD distinct=254 was a stale-BO artifact, now refuted by the clean zeroed-BO oracle. Only a full power-cycle re-arms — impractical per-op for an LLM.)

Board, rocket.spread_confirm=1 (branch rk3576-spread-confirm 4b2590be7), regime = per-op independent
single-task submits (mesa ROCKET_TILE_JOBS=1, NO ROCKET_WHOLE_GRAPH) + zero_out_bos=1. Each op is its OWN
single-task drm job (task_count=1 confirmed on every line) — own PC kick, own regcmd, own perf-clear — on a
warm-powered pipeline (autosuspend keeps the NPU on across the ~40 tile-jobs of one inference; PART 1). Clean
oracle = out_class over the WHOLE pre-zeroed primary output BO (nz), NOT final-BO distinct.
- **361 spread lines across 2 inferences. Exactly 2 REAL — BOTH are op=0** (19.24s + 55.79s, one per
  inference; nz≈400k/802k min00 maxff = real feature map). **358 EMPTY** (nz=0 — not even zero-point written)
  = every non-first op in both inferences.
- **DECISIVE data point = op1:** it reads op0's REAL output (real input in DRAM), is its own independent
  submit, and still writes nz=0 (EMPTY). Reading real data as a non-first submit STILL does not compute →
  same position/cold-start wall.
- **VERDICT: per-op independent submits do NOT re-arm the CSC. The dispatch-granularity ESCAPE HATCH is
  CLOSED.** The SPREAD distinct=254 "COMPUTED" was a STALE-BO artifact (the weak distinct oracle on a reused
  final BO); the clean zeroed-BO nz oracle refutes it.
- **Mechanism sharpened: the cold-start arm is PER-POWER-SESSION (per NPU resume), NOT per-submit.** The two
  REALs are exactly the two inferences' first ops, separated by ~35s of autosuspend→power-down→resume. A
  power-cycle re-arms (both op0 compute); a new submit WITHOUT a power-cycle does not (all ops 1+ within one
  powered session are EMPTY). Within one inference the ~40 tile-jobs are 20-30ms apart = no autosuspend gap =
  one power session = only op0 arms.
- **Note (per-op-dispatch is strictly WORSE than whole-graph chained for later layers):** here non-first ops
  write nz=0 EMPTY (don't even engage the DPU); in the warm whole-graph chain they at least engaged and wrote
  0x80 ZEROPOINT. Matches mesa's own note that a standalone non-first kick "never engages." Either way neither
  produces REAL.
- **Metric-discipline caveat:** core_dt_wr=25088 is IDENTICAL on every line (even EMPTY ones) — the perf
  counter is NOT cleared/read cleanly across separate jobs (frozen at op0's value), so dt_wr is NOT a valid
  per-op oracle in this mode. The pre-zeroed BO nz/out_class IS. Good thing both were logged. [[feedback-metric-discipline]]
- **LLM/matmul consequence:** a matmul/LLM dispatched as independent per-op submits would have ONLY the first
  matmul compute, all others EMPTY — useless. The only thing that re-arms is a full power-cycle (genpd
  down+up + IOMMU re-attach + CBUF re-init) BETWEEN every op; for an LLM with thousands of matmuls/token that
  is catastrophic throughput — a correctness-PoC option at most, not a viable path. [[project-rk3576-dispatch-step2]]
- **Where this leaves it:** the escape hatch (bypass the wall via dispatch granularity) is CLOSED. Back to
  attacking the wall itself (RTL / extract-replay), or the impractical power-cycle-per-op route only to prove
  correctness.

## 2026-07-05 (READ-MARGIN CLOSED — the one concrete non-NPU-block GRF diff, written voltage-matched, has ZERO effect on the chained CMAC. The strongest platform-software candidate for the CBUF-SRAM wall is spent, and its null result undercuts the whole CBUF-timing theme. All thematically-aligned software/platform levers now exhausted → the consume-arm is internal cold-start sequencer state.)

Board, rocket.read_margin (branch rk3576-read-margin): write the vendor's npu_grf SRAM read-margin
(0x26018000 + 0x08/0x0c/0x10) matched to rocket's actual voltage, at runtime_resume. A (read_margin=0,
default) vs B (read_margin=1) with an autosuspend gap so B lands on the next resume.
- **The write LANDED, voltage-matched:** `rocket rm: v=750mV rm=3 wrote 0x001c000c/0x003c000c/0x001c000c to
  grf+0x08/0x0c/0x10 (row 675mV) readback 0x0000140c/0x003c000c/0x0004000c`. rocket runs at **750 mV** →
  **rm=3** (correct per the vendor table row 675 mV, since 675≤750<765). Readback confirms the rm field
  (bits 2-4) = 3 landed: 0x08 `..140c` and 0x10 `..000c` both have bits 2-4 = 3 (0x0c s/2); 0x0c stored the
  full value. So the read-margin IS set to the exact voltage-matched vendor value.
- **A vs B chained output: BYTE-IDENTICAL.** task0 conv0 REAL; task1/2 = 0x80 zero-point; task3/4 = {0d,7f}
  degenerate; task5 = 0x80; task6..28 = 0x00. The read-margin changed NOTHING.
- **VERDICT: read-margin CLOSED (candidate #1 from GRF-PLATFORM-REVIEW).** And this is stronger than one
  null: the read-margin is the MOST DIRECT on-chip SRAM read-timing control, set correctly (rm matched to
  voltage), with zero effect on the chained CMAC → it also **undercuts the whole CBUF-SRAM-timing theme**, so
  the remaining timing candidate (#2 CBUF clock rate) is thematically weakened too. What technically remains
  (CBUF clock, operating point) is weaker AND undermined by this null.
- **The platform-software dimension is now matched where it thematically matters.** Combined with the
  exhausted NPU-software surface (writel audit + byte-matched Phase B trailer + bare native task_number=N HW
  iteration) and ruled-out firmware (same vendor SPI TF-A+OP-TEE): every concrete, thematically-aligned
  software/platform lever is spent. The chained CMAC's CBUF→CSC→CMAC consume-arm is internal cold-start
  sequencer state the vendor's chip carries through its HW iteration and rocket's doesn't — not reachable by
  NPU registers, driver writes, dispatch grammar, firmware, or the SRAM read-margin. Paths left:
  extract-replay / lean on Tomeu's working RK3588 int8 recipe [[project-rk3588-int8-is-solved]] / RTL.
  [[project-rk3576-no-writel-gap]]

## 2026-07-05 (BARE task_number=N CONFIRMED — native HW iteration (no busy-poll, no driver intervention) is BYTE-IDENTICAL to Phase B: chained CMAC still empty. NPU-software surface EXHAUSTED. Firmware RULED OUT (user boots the VENDOR SPI firmware — Rockchip TF-A + OP-TEE — under the mainline buildroot image, so BL31/BL32/OP-TEE is the SAME as the vendor, not the cause). Remaining dimension = the kernel's NON-NPU register spaces (GRF/CRU/power/syscon) that the NPU-block writel audit structurally missed, + mesa.)

Board, rocket.bare_tasknum (branch rk3576-bare-tasknum be86a968a): skip the per-run cnalive busy-poll so the
PC iterates task_number=N natively with ZERO driver register access during the run. Run A (busy-poll) vs
B (bare):
- **A == B, byte-identical.** conv0 distinct=240/241 REAL; task1/2 all 0x80; task3/4 distinct=3 {0d,7f,80};
  task5 distinct=2 nz=896; task6..28 all 0x00. Stripping the busy-poll changed NOTHING.
- `rocket bare: TASK_STATUS=6 top_wt_rd=332 core_wt_rd=0 top_dt_rd=110208` — chained weights AND inputs
  DMA'd to CBUF (top_wt_rd grew past conv0's ~36; top_dt_rd=110208), PC walked 6 tasks, yet chained CMAC
  empty. (core wt_rd=0 is NORMAL, not the oracle.)
- **VERDICT: bare native HW iteration does NOT self-arm the CSC on rocket.** rocket now runs the vendor's
  EXACT dispatch mechanism (byte-matched trailer + native task_number=N iteration + no per-task intervention
  + operands staged into CBUF) and the chained CMAC is still empty — so the rocket-vs-vendor gap is NOT in
  the NPU software (registers/regcmd/dispatch/init all matched AND now exercised in the vendor's own mode).
- **Firmware RULED OUT (new fact from the user):** the board boots the vendor's SPI firmware (Rockchip TF-A
  + OP-TEE) under the mainline buildroot rootfs -> the secure/firmware side is IDENTICAL to the vendor's, so
  a BL31/BL32/OP-TEE-SMC difference is NOT the cause. Supersedes the earlier "mesa=mainline TF-A/no OP-TEE"
  firmware lead as the explanation.
- **Remaining dimension (the one the audit structurally missed):** the writel audit covered ONLY the NPU
  register block (0x2770_xxxx). It did NOT cover GRF / CRU / power-domain / PVTPLL / memory-repair /
  syscon-regmap. RK SoCs commonly place NPU mode/repair/PVTPLL/enable bits in GRF, not the NPU block. A GRF
  (or CRU/power) bit the vendor sets that rocket + the DTS don't would look EXACTLY like this. Being chased
  (read-only enumeration of vendor rknpu's regmap/GRF/CRU/power writes vs rocket + DTS). [[project-rk3576-no-writel-gap]]
  [[project-rk3576-firmware-bl31-bl32]]

## 2026-07-05 (SESSION CLOSE-OUT — dispatch/iteration half SOLVED (upstreamable); wall localized to the CBUF->CSC->CMAC cold-start consume-arm; full software-lever ledger; per-task CSC-rearm (PP_CLEAR) CLOSED. Software surface exhausted -> RTL, with ONE standing software question (bare task_number=N).)

**WHAT IS NOW SOLVED (dispatch/iteration half — all confirmed working end-to-end, upstreamable):**
- Whole-graph trailer grammar: absolute next-pointer (PC 0x10 = next task's iova) + PC 0x14 amount + SYNC
  0x41 + broadcast OP_EN 0x1d, order [0x10][0x14][SYNC][broadcast], last task terminates 0/0 —
  runtime-confirmed byte-for-byte vs the vendor (task_number=8 dump == compile-time .rknn).
- The mesa rkt_pack_graph_regcmd fix emitting that grammar (key the trailer on ANY in-stream OP_EN —
  broadcast for conv0's firstconv fill OR the 4 per-unit OP_ENs the dw/pw normal fill emits — else only
  conv0 got a next-pointer and the chain broke after 1 hop).
- PC self-iteration via the trailer: trailer chain 29/29 (task0..27 match=YES, task28 LAST), TASK_STATUS
  walks the tasks.
- The TASK_CON upper-control-bit (0x6<<16 iterate-enable) — with it all 4 units engage (exec_ever=0xf, was
  0x8=RDMA-only); the earlier "internal wall" reading was the trailer packer bug, not this.
- Per-task engage + input DMA + weight DMA + per-task weight/CBUF config all correct (weight regcmd present
  per task, sensible sizes: conv0 0x600, depthwise 0x240, ... task28 1MB; DMA clean, RDERR=0/WRERR=0).

**THE REMAINING WALL (precisely localized):** CBUF->CSC->CMAC consume-arm. The chained CMAC never drains
CBUF -> empty accumulator -> requant zero-point. The task-6 stall is a SYMPTOM (CMAC doesn't drain -> CBUF
fills after ~6 layers -> PC can't stage layer 7). One coherent cause: the CSC consume/weight-load stage arms
only on the cold-start task — the mechanism-level, fully-cornered form of "only the cold-start task MACs."
(NB core wt_rd=0 is NORMAL, vendor too; not an oracle. The oracle is the zero-point output with data
confirmed in CBUF by the earlier CBUF audit.)

**SOFTWARE-LEVER LEDGER (tried against the consume-arm, result):**
- geom_all — forced every regcmd register into both PP groups -> no arm (regressed conv0).
- writel audit (vendor vs rocket, full driver enumeration + 1-task & 2-task captures) -> NO NPU register the
  vendor writes that rocket doesn't; descriptor-DMA falsified (task_number=2, base=0).
- pp_alt (alternate ping-pong PRODUCER pointer per task) -> reached the write path, not the MAC arm.
- Phase B trailer (runtime-exact vendor grammar) -> iteration + engage work, MAC still empty.
- per-task PP_CLEAR / CSC-rearm in the trailer -> did NOT reach CSC_WL; REGRESSED (chained tasks went fully
  inert 0x00 instead of writing zero-point 0x80). CLOSED.
- vendor per-task trailer contains NO re-arm entry to copy (S_POINTER 0x0e, no PP_CLEAR) -> its per-task
  re-arm is internal to the PC HW iteration.

**STANDING QUESTION (~~still open, NOT closed~~ — ANSWERED 2026-07-13, see below):** rocket has never actually run the vendor's bare
task_number=N HW-iteration mode (wg_continuous always wedged pre-trailer-fix, then was replaced by the
trailer-walk / seq-kick). Whether that bare mode self-arms the CSC is the one remaining software-side
question before committing fully to RTL. See CSC-CONSUME-REVIEW.md, WHOLEGRAPH-GRAMMAR.md.
[[project-rk3576-no-writel-gap]]

> **ANSWERED 2026-07-13 by the dual-image replay — do NOT re-chase bare task_number=N.**
> The closed-vs-open cross-check (`FINDINGS-DUAL-IMAGE.md`) ran `replay_rocket`, which
> replays the vendor's OWN captured regcmd bytes through the rocket driver in
> `task_number=N` mode — i.e. exactly the bare vendor HW-iteration stream this question
> asked about. It STILL walls (chained CMAC empty). So the bare task_number=N mode does
> NOT self-arm the CSC on rocket even when driven by the vendor's exact byte stream. This
> was the last remaining software-side question; with it answered negative, the RTL /
> internal-cold-start-sequencer reading is the justified conclusion, not just the
> converged one.

## 2026-07-05 (DISPATCH/ITERATION HALF CLOSED — trailer chain 29/29 perfect, weight regcmd present+plausible every task, all 4 units engage, DMA clean; YET chained CMAC empty. The wall is now precisely localized to ONE stage: CBUF->CSC->CMAC consumption. Converges with the earlier CBUF audit. The task-6 stall is a SYMPTOM: CMAC doesn't drain CBUF -> operands pile up -> the fixed CBUF fills after ~6 layers -> PC can't stage layer 7.)

Board, whole-graph one-submit, mesa Phase B fix + kernel trlchk-all-tasks (branch rk3576-weightfetch
5c9925792). The all-task trailer + weight dump settles both open questions:
- **Trailer chain PERFECT end-to-end (29/29):** task0..27 match=YES (pc10 == the next task's regcmd iova
  exactly), task28 match=LAST (pc10=0 terminator), sync=1 bcast=1 on EVERY task. So the task-6 stall is NOT
  a chain break -- the chain is intact all the way.
- **Weight regcmd PRESENT + PLAUSIBLE every task:** each has a real weight addr (0x1110) + byte-count
  (0x101c) with sensible per-layer sizes -- conv0 wtsz=0x600 (1536), depthwise wtsz=0x240 (576 = 9*64, the
  dw signature), pointwise/conv 0x2000/0x4000/0x8000..., task28 0x100000 (1 MB). NOT missing, NOT zero =>
  NOT a mesa weight-regcmd bug. (cbuf CBUF_CON0 0x1040 also set: 0x10000000 / 0x14000000 per task.)
- **VERDICT -- dispatch/iteration half is CLOSED and CORRECT:** trailer grammar, PC self-iteration, per-task
  engage (exec_ever=0xf all 4 units), input DMA, weight DMA, and per-task weight+CBUF config are ALL
  confirmed working/correct, reproduced end-to-end in a single whole-graph submit. The remaining wall is one
  specific pipeline stage: **CBUF->CSC->CMAC consumption** -- the operands reach CBUF (earlier CBUF audit
  proved data lands in CBUF) but the CMAC never drains/consumes them, so every chained layer outputs
  zero-point. Same stage the earlier CBUF audit fingered, now cornered with everything upstream eliminated.
- **task-6 stall = a SYMPTOM of the same cause, not a separate bug:** if the CMAC doesn't drain CBUF, each
  layer's staged operands accumulate in the fixed on-chip CBUF -> it fills after ~6 layers -> the PC can't
  stage the 7th -> stalls (PC_DONE fired fast, ~10 ms, not a poll-cap timeout). One coherent root: the CSC
  consume/weight-load stage arms only on the cold-start task (the mechanism-level form of the long-standing
  "only cold-start MACs" / "input reads but weights don't" wall). Next: attack the CBUF->CSC->CMAC stage
  directly; review (rk3576-weightfetch report) whether the CSC consume/drain trigger was ever touched vs
  only the CBUF-side staging/reset. [[project-rk3576-no-writel-gap]]

## 2026-07-05 (PHASE B TRAILER FIX — REVERSES the premature "internal wall" verdict. The mesa packer keyed the trailer on the broadcast OP_EN (0x81/0x08), which ONLY conv0's firstconv fill emits; the dw/pw normal fill emits 4 PER-UNIT OP_ENs by default -> only conv0 got a next-pointer -> the chain broke after 1 hop. Fixed to key on ANY in-stream OP_EN. Board: trlchk all match=YES, exec_ever=0xf (all 4 units engage, was 0x8), PC walks 6 tasks (TASK_STATUS=6, was 1), dt_rd=110208, RDERR=0/WRERR=0, clean PC_DONE. Trailer + iteration CONFIRMED WORKING. Remaining wall is NARROW: chained outputs still zero-point (empty accumulator) despite all units engaging + reading input. NB the reversal was the TRAILER FIX, not TASK_CON (that confound was refuted analytically, never built). **CORRECTION (metric discipline): my first read "core wt_rd=0 = chained fetch no weights" was WRONG -- core wt_rd=0 is NORMAL (vendor capture too: top[wt_rd=36] core[wt_rd=0]); weights count in TOP wt_rd (=332 here, cumulative, grew beyond conv0's ~36 so it can't prove chained fetch nothing). Real remaining wall = the earlier "operands don't reach the CMAC from CBUF, independent of content" (CBUF->CSC->CMAC staging), now in a working whole-graph walk. The rk3576-weightfetch diagnostic checks the per-task weight regcmd + the trailer past task 2.**)

Board, whole-graph one-submit, mesa Phase B FIX (branch rk3576-wholegraph-trailer 8ff472f) + kernel
rocket.trailer_check=1 (branch rk3576-trailer-check 3b48f285b).
- **Root cause of the earlier 1-hop stall = a mesa packer bug, NOT the HW wall.** The packer located the
  per-task trailer by scanning for the broadcast OP_EN (tgt 0x81 reg 0x08). But only conv0 uses the
  firstconv fill (which emits the broadcast); every dw/pw uses the normal fill, which by DEFAULT emits FOUR
  per-unit OP_ENs (CNA 0x1008/CORE 0x3008/DPU 0x4008/RDMA 0x5008), no broadcast. So the scan matched conv0
  only -> only conv0 got a next-pointer -> board trlchk task0 match=YES, task1+ NO-PC10 -> the PC walked one
  hop and stalled. Fix: key the trailer on ANY in-stream OP_EN (broadcast OR per-unit), so every task gets
  [0x10 abs next][0x14 amount][SYNC][broadcast].
- **After the fix (board):** trlchk task0/1/2 all match=YES (next-ptr == next task's iova). exec_ever=0xf
  (CNA+CORE+DPU+RDMA all engage on chained tasks, was 0x8=RDMA-only). PC walks to TASK_STATUS=6 (was ~1).
  top dt_rd=110208 (many layers' input read), core dt_wr=100464, RDERR=0 WRERR=0, PC_DONE fired ~10 ms
  (fast, not a poll-cap timeout). So the trailer + PC self-iteration + per-task engage are CONFIRMED WORKING
  -- the earlier "internal wall" verdict was premature (it was the packer bug).
- **Remaining wall (narrow):** chained outputs still zero-point -- conv0 distinct=243 REAL; task1 distinct=1
  all 0x80; task2 0x80; task3/4 distinct=3 {0d,7f,80}; task5 partial -- empty accumulator despite all units
  engaging + reading input.
- **CORRECTION (metric discipline, my misread):** I first called `core wt_rd=0` the oracle for "chained
  fetch no weights." WRONG -- core wt_rd=0 is NORMAL: the vendor's own est capture reads top[wt_rd=36]
  core[wt_rd=0] (weights count in TOP wt_rd, not core). Our run top wt_rd=332 is CUMULATIVE and grew beyond
  conv0's ~36, so it cannot prove chained layers fetch nothing. So "no weight fetch" is UNPROVEN. The actual
  earlier localization (single-task work, [[project-rk3576-conv0-weightlayout]] / [[project-rk3576-dispatch-step2]])
  was **"the CMAC operands (weights and/or input) do NOT reach the CMAC from CBUF, INDEPENDENT of weight
  content"** -- a CBUF->CSC->CMAC staging issue, not a weight-DMA or weight-value bug. That is the same wall,
  now reproduced inside a working whole-graph walk.
- **Two open sub-questions:** (a) whether the chained weight regcmd (CNA 0x1110 addr / 0x101c size) is even
  present + plausible per task (the diagnostic checks this) vs the operands staging into CBUF but not
  reaching the CMAC; (b) why the PC stops at task 6 not 29 (fast PC_DONE, not a timeout) -- possibly the
  trailer breaks past task 2 (trlchk only checked 0-2) or a downstream stall. Being chased (branch
  rk3576-weightfetch): extend trlchk to ALL tasks + dump per-task weight regcmd. See WHOLEGRAPH-GRAMMAR.md.

## 2026-07-05 (PHASE B board result — the runtime-exact trailer makes the PC self-iterate ONE hop (dt_rd=29792 = conv0+task1, TASK_STATUS 0->2, task1 engages+reads+writes) but task1's MAC is EMPTY (output all 0x80 = requant zero-point) and the PC stalls after ~1 task (task2+ untouched, 0x00). Matches the earlier ROCKET_NEXTPTR one-hop result; the exact trailer (broadcast+SYNC+abs-ptr) did not advance further. NOT yet "#1 closed": a TASK_CON latch CONFOUND is flagged — kernel WROTE PC TASK_CON=0x0007001d but the readback = 0x0001001d (the 0x6<<16 iterate-control bits absent). Resolving whether those bits latch (post-exec clear vs real write-failure) BEFORE any RTL verdict.)

Board, whole-graph one-submit (mesa Phase B branch rk3576-wholegraph-trailer 1233c5f: emit the vendor
trailer [PC 0x10 abs next][PC 0x14 amount][SYNC 0x41][BROADCAST OP_EN 0x1d] per task) + kernel
rocket.wg_continuous=1 + zero_out_bos=1. task_count=29, ONE submit (TASK_CON=0x…001d, DATA_ADDR=0xfe22c000,
DATA_AMOUNT=0x49).
- **Trailer advanced the PC (old wg_continuous wedged at task 0):** top dt_rd=29792 = conv0 (9408) + task1
  (20384) input BOTH read; TASK_STATUS 0->2; task1 engaged, read its input, and WROTE its output.
- **But chained MAC still EMPTY (zero_out_bos oracle):** conv0 (task0) distinct=240 min00maxff REAL; task1
  distinct=1 all 0x80 (WROTE, but zero-point = empty accumulator); task2..28 distinct=1 all 0x00 (untouched,
  PC stalled after ~1 hop, PC_DONE fired ~9ms, samples=1). No chained task computed a real feature map.
- Same "only cold-start task MACs" wall; trailer solved ITERATION (advance) not the chained-MAC arm.
  Reproduces the earlier ROCKET_NEXTPTR one-hop-then-stall; the runtime-exact additions (kept broadcast,
  SYNC, absolute next-ptr) did not improve on it.
- **CONFOUND before the RTL verdict:** TASK_CON write 0x0007001d vs readback 0x0001001d (only bit16 present,
  the 0x6<<16 control bits gone). If 0x6<<16 is the "iterate N tasks" enable and it did not latch, the PC
  may be 1-shot-committing, not N-walking -> Phase B never truly tested vendor-grammar iteration and the
  1-hop-empty result is a control-bit artifact, NOT proof of an internal arm wall. Being resolved (branch
  rk3576-taskcon-latch): 3-point TASK_CON readback (before OP_EN / after OP_EN / at completion) + vendor
  TASK_CON write-path diff. Same class of confound as the earlier "broadcast restarts the PC" (a mis-set
  next-pointer). #1 is NOT closed until this is cleared.

## 2026-07-05 (WHOLE-GRAPH GRAMMAR runtime-CONFIRMED — GO on Phase B (mesa). A runtime dump of the vendor's task_number=8 submit buffer EXACTLY matches the compile-time .rknn (librknnrt does NOT rewrite the trailer): each task ends with a self-iteration trailer [PC 0x10 = ABSOLUTE next regcmd_addr][PC 0x14 = 0x47 amount][SYNC 0x41][BROADCAST OP_EN 0x81/0x08 = 0x1d]. mesa RK3576 whole-graph deviates on all three; Phase B copies the confirmed grammar.)

Board, vendor kernel + rknpu.trailer_dump=1 (branch rk3576-runtime-trailer 4daa62ae1), whole-graph chain
(task_number=8, task_base_addr=0x0). Dumped the first 3 tasks' trailer (read PAST regcfg_amount where the
+4 EXTRA lives). Three VERDICT lines:
- **OP_EN = BROADCAST** (tgt 0x81 reg 0x08 = 0x1d), NOT per-unit -- every task. Settles the biggest mesa
  deviation (the RK3576 packer replaces the broadcast with 4 per-unit OP_ENs).
- **PC 0x10 next-pointer = ABSOLUTE**: T0 0x10 = 0xffff7980 == T1's regcmd_addr exactly; T1 -> 0xffff7e00
  (T2), T2 -> 0xffff8280 (T3). librknnrt patches it to the absolute iova at load. (mesa ROCKET_NEXTPTR math
  = graph_addr + (g+1)*stride already yields this.) PC 0x14 = 0x47 = pc_data_amount.
- **SYNC 0x41 present** at trailer position [141]; order [0x10][0x14][SYNC][broadcast].
- Structure confirmed: each task = 139 config [0..138] + 4 trailer [139..142] + pad [143], 0x480 (=144 u64)
  contiguous stride; T0..T3 regcmd_addr = 0xffff7500/7980/7e00/8280.
- **The mesa "broadcast 0x08 RESTARTS the PC" note was a CONFOUND**: broadcast re-fires with PC 0x10 still
  pointing at the CURRENT task (no next-pointer) -> re-runs the same task -> looks like a restart. With the
  absolute next-pointer written BEFORE the broadcast, it commits-and-advances. Order is load-bearing.
- **GO, runtime-confirmed** (upgrades the earlier compile-time GO). Phase B (mesa rkt_pack_graph_regcmd):
  emit per task [139 config][PC 0x10 abs next = graph_base+(g+1)*stride][PC 0x14 amount][SYNC 0x41][BROADCAST
  0x1d], last task next-ptr = 0; drop the per-unit substitution; kernel unchanged (task_number=N stop-count).
  See WHOLEGRAPH-GRAMMAR.md. [[project-rk3576-no-writel-gap]]

## 2026-07-05 (pp_alt (candidate #2) CLOSED — alternating the seq-kick producer ping-pong group does NOT arm any chained-layer MAC. Board, seq-kick+warm-chain, clean output-distinct oracle: conv0 real / every chained task empty in BOTH pp_alt=0 and =1. Confirmed TRUE NEGATIVE, not a no-op: pp_alt=1 flipped task1's output from untouched 0x00 to written zero-point 0x80 — the regcmd patch reached HW and moved the WRITE path, but the MAC accumulator stays empty. The arm is below the register/config level, as geom_both + pure-position already implied.)

Board (branch rk3576-pp-pointer a75db5cdc, LOCAL; rocket.pp_alt): the seq-kick producer S_POINTER POINTER
is hardcoded 0 every kick; pp_alt alternates it by per-job task index (task 0 -> group 0 control unchanged,
odd -> group 1), patching the regcmd's own CNA 0x1004 / CORE 0x3004 entries in DRAM too (the driver write
alone is overwritten mid-run by those entries). S98mndump ran the pp_alt=0 baseline; pp_alt=1 over serial.
- **Every chained task empty in BOTH modes (output-distinct oracle, NOT dt_wr).** pp_alt=0: conv0 (task0)
  distinct=240 min00 maxff REAL, task1 distinct=1 all-0x00, task2..28 distinct<=3 (zero-point). pp_alt=1:
  conv0 distinct=241 REAL, task1 distinct=1 all-**0x80**, task2..28 distinct<=3. No task>=1 ever reaches a
  real feature map (the lone distinct=3 is task3's {0d,7f,80} = zero-point +/-1, present identically in
  both runs). Every task engages (cna_eng=1 core_eng=1) in both.
- **TRUE NEGATIVE, not "didn't take effect."** The pp lines show prod correctly alternating (task odd
  prod=1, even prod=0, task0 prod=0), and task1's output BO flipped from baseline `0x00 nz=0/4096`
  (untouched) to pp_alt=1 `0x80 nz=4096/4096` (written full zero-point). So the regcmd patch DID reach the
  hardware and changed the DPU write path -- but the accumulator is still empty (empty MAC -> requant ->
  zero-point 0x80). Group alternation touches the pipeline, not the MAC arm.
- **CLOSED.** Consistent with geom_both (config in BOTH groups didn't arm dw1) and pure position ("only
  task 0 computes" is inconsistent with a stuck-producer/advancing-consumer story, which predicts 0/2/4).
  Directly measured now. NOTE (reusable): the consumer group is NOT a readable index -- CNA/CORE S_POINTER
  bit0 = producer echo, bit16 = executer engage-status; exec_ever + the output-distinct oracle are the real
  signals, not a consumer-group read, and dt_wr counts zero-point writes so it is not a clean compute
  oracle. The only lever left is #1 (mesa regcmd laid out for the PC's own task auto-advance = the vendor
  whole-graph grammar), which is a mesa change, not a kernel one.

## 2026-07-04 (WRITEL AUDIT — complete static enumeration of EVERY NPU register write, both drivers, across a FULL inference: NO writel the vendor makes that rocket does not. task_base_addr=0 even for task_number=2 REFUTES the descriptor-DMA idea. The difference is grammar (one submit / PC iterates N vs seq-kick N kicks), not a missing register. Live writel-trace built into both stacks for the decisive runtime diff. See WRITEL-AUDIT.md.)

Part 1 (read-only) enumerated every NPU-register writel in the vendor rknpu driver (rk3576-vendor-kernel/
drivers/rknpu/, RK3576 config) across ALL functions, and every write in rocket's default path, then diffed
against BOTH captured vendor logs. **Decisive facts:**
- **task_base_addr=0 even for task_number=2.** dirty/vendor.txt holds a real MULTI-task vendor capture:
  `SUBMIT task_number=2 ... task_con=0x70002 task_base_addr=0x0 pc_dma_ctrl=1`. The vendor iterates 2 tasks
  from ONE submit with PC_DMA_BASE_ADDR(0x34)=0. This **kills the descriptor-DMA dispatch theory** outright
  (the prior "descriptor experiment was wrong" note rested on a single-task capture; now the multi-task one
  confirms it directly). rocket writes 0x34=0 too -> not a gap. Do NOT re-explore PC_DMA_BASE_ADDR.
- **The per-submit register sequence is identical** (reconfirmed vs 1-task vendor-live-cap.txt AND 2-task
  dirty/vendor.txt). Vendor RK3576 NPU writes, complete set: state_init (probe/reset: 0x10=1, 0x1004 toggle
  0/1/0x1e, 0x1024=0x80000000 x2); per submit (subcore_commit+commit_pc): 0x10=1(slave), 0x1004=0xe,
  0x3004=0xe (num_irqs=2>1), 0x10=regcmd, 0x14=amount, 0x20=0x300, 0x24=0x300, 0x30=((0x6|pp)<<16)|N,
  0x34=task_base_addr(=0), 0x8=1, 0x8=0; per IRQ: 0x24=0x1ffff; perf clear 0x2210/0x2410. NO other NPU
  write anywhere -- the action ioctl exposes no register write, bw_priority disabled on RK3576
  (bw_priority_addr=0), NO register-BAR mmap, power/clk via frameworks, NBUF via IOMMU map not writel.
- **VERDICT: no register offset the vendor writes and rocket never does.** The only multiset differences are
  rocket writing MORE (per-job pp_state_init; 0x24 also clearing PC_DONE). The vendor's sole advantage is
  STRUCTURAL: one submit + task_number=N, PC hardware iterates all N tasks from one OP_EN (ping-pong group
  advances in HW; next task's regcmd found from the regcmd stream since base=0). Not a kernel writel.
- **Ranked candidates:** #1 [mesa, NOT kernel] regcmd not laid out for PC auto-advance -- vendor whole graph
  is one task_number=N submit, PC strides via regcmd stream + the +4 EXTRA amount stride; mesa emits the
  next-pointer/contiguous layout only for soc!=RK3576. This is wg_continuous's wedge. #2 [kernel, cheap,
  maybe untested cleanly] seq-kick's ping-pong POINTER never advances -- rocket hardcodes pp_pointer=0 every
  kick (pp_task_idx++ computed but unused); try POINTER=pp_task_idx&1 (weak counter-indication: geom_both
  forced config into both groups, not the executer's per-task active-group select). #3 perjob_ppinit (rocket
  writes MORE not less; low prior).
- **Part 2 (built, NOT flashed):** rknpu.wtrace / rocket.wtrace log `... wt <seq> <abs_off> <val> <caller>`
  for every NPU write (same absolute offsets both stacks; reset-on-arm; capped 20000). Differ:
  vendor-capture/diff_writel_trace.py aligns by offset seq, drops the vendor capture-build instrumentation,
  prints vendor-only/rocket-only + per-register counts + verdict (self-tested). Branch rk3576-writel-trace,
  LOCAL: vendor 763eae8c8, rocket b60af5ebf; both compile clean aarch64 (rknpu_drv/job.o, rocket_core/job.o).
  Report+differ pushed to linux-rk3576-npu main 9e6e794. Next: flash, capture both, run differ -- if it
  prints nothing (static read predicts so) the search leaves the register file for the one-vs-many-submit
  grammar (mesa regcmd chaining), or test cheap candidate #2.

## 2026-07-04 (LOOSE END CLOSED — zero_out_bos (stale-proof) confirms chained layers write NOTHING real and dt_wr is a cumulative counter. conv0 writes a genuine feature map (distinct=232) to its own pre-zeroed BO; dw1/task2/task3 are distinct<=2 (EMPTY/ZEROPOINT) in every dump with zeroing on. The software-structural line is cleanly closed: the wall is below the registers, only the cold-start task MACs.)

Board, seq-kick + warm-chain, rocket.zero_out_bos=1 (kernel branch rk3576-bo-groundtruth a3c67f7c1: memset
every output BO to 0 + flush before the job kicks; per-completion readback + a finalize whole-BO classify;
per-completion core dt_wr delta). The zeroing removes the conv0_twice stale-data trap: any post-run
non-zero is a definitive write this run.
- **dt_wr is CUMULATIVE.** Per-completion core dt_wr deltas: conv0=25088, dw1=+20160, task2=+4928, ...
  (25088, 45248, 50176, ...). Running totals, not per-kick output sizes -- the "large early dt_wr" that
  nagged the open_high result is a cumulative-counter artifact, now settled.
- **Chained layers write NOTHING real (stale-proof).** With the BOs pre-zeroed, the per-completion readback
  reads: dw1 (0xfea69000) distinct=1 every dump (some min=80 = zero-point); task2 distinct<=2; task3
  distinct<=3 (min0d max80, still zero-point-ish). No chained output is a real feature map, and none holds
  mis-routed real data. Outcome (1)/(2), NOT the reversal (3).
- **conv0's real output is GENUINE, not stale.** conv0 (0xfeb2d000) reads distinct=232 (min00 max ff) in a
  BO that was zeroed immediately before the run -> conv0 truly wrote it this run. (conv0 also reads
  distinct=1 in the warm inferences, definitively empty -- consistent with cold-start-only.)
- **Self-correction on the diagnostic:** my finalize whole-BO groundtruth block read conv0 EMPTY and I
  first misread that as "conv0 doesn't land." It was an artifact: each inference runs a main job + a tiny
  tail job, and zero_out_bos runs PER JOB, so the tail job re-zeroed bo0 AFTER the main job's conv0 wrote
  it, and the finalize scan (running in the tail job) saw bo0 zeroed. The per-completion readback -- which
  catches conv0's 232 mid-run -- is the truth. The zeroing worked; only the per-job placement of the
  finalize scan was wrong (harmless, diagnostic-only).
- **Landing:** every stale-data confound is now removed and the conclusion holds byte-for-byte: only the
  first task after NPU-init writes a real feature map; every chained layer's output is definitively empty.
  Combined with the byte-identical per-kick register sequence, the matched completion handshake, the
  refuted OP_EN-high timing, and geom_all (no regcmd register is the arm), the RK3588->RK3576
  software-structural line is exhausted. The switch that arms the CMAC for the cold-start task and only it
  is below the last writable register -- NVDLA CSC/CMAC sequencer state / an RK3576 quirk, not a driver fix.

## 2026-07-04 (open_high (OP_EN-high, upstream RK3588 model) REFUTED — dw1's output BO is distinct=1 in BOTH open_high=0 and =1, no completion timeout. The last per-kick structural difference from RK3588 did not arm the chained layer. CAVEAT/loose-end: the per-completion core dt_wr counters show large early values (25088->45248->50176->90944->100352) that don't square with "only conv0 computes"; core dt_rd is clearly cumulative, so dt_wr is likely a cumulative/dirty-counter artifact, but this isn't 100% nailed. open_high shifted the collapse point by one completion (A idle at #6, B does one more real read+write).)

Board A/B, seq-kick + warm-chain, rocket.open_high (kernel branch rk3576-openhigh 5f404abb8: drop the
submit OP_EN=0 pulse, leave OP_EN high through execution, complete on DPU-done bits 8/9; unconditional
300 ms poll cap). RUN A open_high=0 vs RUN B open_high=1:
- **dw1 (task=1) output BO 0xfea69000 = distinct=1 in BOTH A and B** (all 0x00 or all 0x80 zero-point).
  The all-tasks readback -- the direct read of dw1's declared output -- is empty either way. **open_high
  did not unlock the chained layer.** No "seq-kick poll TIMEOUT" fired (completion worked; the DPU-done
  path/poll completed within the cap), so the poll-cap safety net held without engaging.
- **Verdict: the OP_EN-high (upstream) model is refuted as the per-task arm.** Together with the
  byte-identical per-kick register sequence and the already-matching completion handshake, the RK3588 ->
  RK3576 software-structural per-kick line is essentially exhausted.
- **CAVEAT (unresolved):** per-completion core dt_wr = 25088, 25088, 45248, 50176, 90944, then 63... (A)
  / ...100352 then 63 (B). Large values for the first ~5-6 completions. core dt_rd is unmistakably
  cumulative (91,178,265,372,... resets at inference boundaries), so core dt_wr is most likely also a
  cumulative/uncleared counter, not a per-kick output size -- in which case the readback (dw1 empty) is
  the truth. But if dt_wr were per-kick it would mean the early layers write substantial data somewhere
  other than their readback'd output BO, which would overturn "only conv0 computes". Not double-handling
  (consecutive done-lines are ~12 ms apart, 132 completions ~= 4-5 inferences x 29 tasks). A vs B diverge
  only at completion 6 (A top_rd=64/dt_wr=63, B top_rd=4704/dt_wr=100352) -- open_high pushed the real-work
  run one completion further before collapsing, but no output BO became non-empty.
- **NEXT: nail the dt_wr caveat before declaring the software line closed -- zero each task's output BO
  before its kick and widen the readback beyond the first page, to see whether any early layer writes real
  data anywhere. If all still empty -> cleanly pivot below software (NVDLA CSC/CMAC RTL / RK3576 quirk); if
  an early layer writes real data elsewhere -> that reopens the whole model.**

## 2026-07-04 (conv0_twice CONFIRMS pure position — even conv0's OWN regcmd + external input does NOT MAC when re-run as a non-cold-start kick. The 2nd conv0 (30th kick) has core dt_wr=63 (vs 25088 real) and top dt_rd=0; its output BO's distinct=245 was STALE 1st-run data, not a recompute. distinct is not the oracle, dt_wr is. Only the first task after NPU-init MACs, independent of layer/data/input-source.)

Board (seq-kick + warm-chain, rocket.conv0_twice=1, kernel branch rk3576-arm-hunt 66245517d+18f01a896:
re-run task 0 after the job completes, no reset, then finalise). Per inference the log shows
"rocket conv0_twice: re-running task 0" then the replay's completion:
- **1st conv0 (cold-start):** core dt_wr=**25088**, top dt_rd=9408 wt_rd=96 -> real MAC.
- **2nd conv0 (replay, ~30th kick):** core dt_wr=**63**, top dt_rd=**0** -> did NOT DMA its input and wrote
  essentially nothing. Its output BO still read distinct=245 with byte-identical first bytes
  (b7 7f ea e5 ...) to the 1st run = STALE, never overwritten. **The 2nd conv0 did NOT compute.**
- **VERDICT: PURE POSITION, confirmed and now directly measured.** conv0's exact regcmd + the same external
  input, run as a non-first-after-init kick, produces no MAC. So the gate is NOT layer type, NOT data, NOT
  input source -- it is task position: only the first task the PC executes after NPU (re)init arms the CMAC.
- **Metric-discipline note (again):** the 2nd conv0's distinct=245 first read as "it computes" (which would
  have REFUTED position); the perf counter (core dt_wr=63 vs 25088, top dt_rd=0) corrected it to "stale,
  empty". distinct/first-bytes are not a correctness oracle for a re-used BO; core dt_wr is.
- **Ties to the Part 1 #1 hypothesis:** the 2nd conv0 has top dt_rd=0 (even more inert than dw1's 20384) --
  a non-first kick's whole CNA->CBUF->CMAC path fails to arm, consistent with "only the first kick's OP_EN
  (left-high vs our submit-pulse) actually arms the pipeline".
- **NEXT: add a poll cap to the seq-kick completion (so OP_EN-high can't hang -> reset -> iommu death),
  then test Part 1 #1 (leave OP_EN high through execution, upstream-style) -- the top adaptable difference.**

## 2026-07-04 (RK3588-vs-RK3576 task-2+ diff (read-only, upstream pristine rocket at e7d700e14). The per-task register sequence is byte-IDENTICAL to upstream, and our completion handshake already matches/exceeds it. The ONLY per-kick deviation is the seq-kick macro's extra OP_EN=0 pulse AT SUBMIT (upstream leaves OP_EN high during execution). Ranked below. Built the safe conv0_twice position-confirmation knob; did NOT build the OP_EN-high variant (risks an uncapped poll->hang->reset->iommu-death).)

Diffed the pristine upstream RK3588 rocket (linux-next import e7d700e14, 635 lines) against our RK3576
rocket_job.c, the task-2+ path specifically. geom_all already closed the regcmd-register line (see below);
this pins what STRUCTURALLY differs from the WORKING RK3588 path.

- **upstream RK3588 hw_submit (per task, WORKS):** reset check; task=tasks[idx]; idx++; BASE_ADDRESS=0x1;
  CNA S_POINTER = PP_EN|EXECUTER_PP_EN|PP_MODE|extra_bit (0x0e for core 0); CORE S_POINTER same;
  BASE_ADDRESS=task->regcmd; REGISTER_AMOUNTS; INT_MASK=DPU_0|DPU_1 (0x300); INT_CLEAR=DPU_0|DPU_1;
  TASK_CON=RESERVED_0|TASK_COUNT_CLEAR|TASK_NUMBER(1)|TASK_PP_EN; TASK_DMA_BASE_ADDR=0; **OP_EN=1 (only)**.
  Completion (DPU-done IRQ): **OP_EN=0; INT_CLEAR=0x1ffff**; re-kick next or finish. job_run: pm_get +
  iommu_attach + hw_submit -- NO reset/re-init (rocket_core_reset is error-path only).
- **RANKED diff (task-2+ arming candidates):**
  1. **[TOP, concrete, but risky to test] submit-time OP_EN=0 pulse.** Our seq-kick macro pulses OP_EN
     1->0 AT SUBMIT (vendor single-shot style); upstream sets OP_EN=1 and leaves it HIGH through
     execution, clearing to 0 only at completion. For a per-task RE-KICK model (which upstream is and we
     are), the OP_EN=1->0 transition AT COMPLETION may be the HW's per-task commit/re-arm; pulsing at
     submit (OP_EN=0 during execution) skips it. The vendor's submit-pulse works only because the vendor
     uses PC HARDWARE ITERATION (task_number=N, one pulse, PC advances internally) -- not re-kick.
     Adaptation: drop the macro's OP_EN=0, leave OP_EN high, clear at completion (already done at the
     completion site). NOT BUILT: our seq-kick poll waits on PC_DONE with no cap, and PC_DONE may not
     assert while OP_EN is high -> infinite poll -> sched timeout -> rocket_core_reset -> shared rk_iommu
     dies. Needs a poll cap first; flag before flashing.
  2. **[weaker] pp_state_init per-job.** RK3576-only (rocket_core_pp_state_init: S_POINTER PP_CLEAR +
     DS1=0x80000000 to both PP groups). Upstream RK3588 runs it NEVER; vendor RK3576 runs it ONCE at
     probe; we run it at probe AND per-job (perjob_ppinit=1). warm_chain (skip on re-kicks, task 0 still
     gets it) already tested -> engage+DMA, no MAC, so a plain skip is not the fix -- but "only at probe,
     never per-job" (perjob_ppinit=0, matching vendor+upstream) is a distinct, untested config, testable
     with the existing knob and no new code. Risk: may break conv0 (probe-time state stale by inference).
  3. **[not it] completion handshake.** We already do OP_EN=0 + full INT_CLEAR=0x1ffff at completion
     before each re-kick (>= upstream). Matches; ruled out.
  4. **[not it] per-task register values.** Byte-identical to upstream (S_POINTER 0x0e, TASK_CON equiv,
     INT_MASK 0x300, OP_EN=1). Confirms geom_all -- no register value is the miss.
  5. **[not it, intra-job] job_run adds attach-once + tlb_flush** (per-job; a seq-kick graph is ONE job,
     so these don't fire between tasks). mesa: per-task regcmd byte-identical; the next-pointer trailer is
     only used in wg_continuous, not seq-kick.
- **Completion detection differs (poll PC_DONE vs upstream DPU-done IRQ) but the register actions match.**
- **NEXT: test #1 first (highest likelihood) but only after adding a poll cap so OP_EN-high can't hang;
  meanwhile conv0_twice (built, rk3576-arm-hunt 66245517d) gives a 1-flash pure-position verdict.**

## 2026-07-04 (geom_all CLOSES the regcmd-register line — the chained-layer CMAC arm is NOT any regcmd register. dw1 stays distinct=1 with the ENTIRE regcmd config (88 CNA + 8 CORE + 67 DPU + 20 RDMA) CPU-forced, and conv0 CRASHES to distinct=1 (uniform 0xfe). Not CBUF data, not any register -> it is a cold-start internal hardware context.)

Board A/B, seq-kick + warm-chain, rocket.geom_all=1 (kernel branch rk3576-geom-all 7cc4032e1: CPU-write
EVERY regcmd config target -- CNA/CORE into both PP groups + DPU/RDMA once via the driver's dpu_iomem/
dpu_rdma_iomem, skipping the 0x81/0xf008 broadcast and per-block S_POINTER/OP_EN). geom_all fired,
logging "wrote 88 CNA + 8 CORE (both groups) + 67 DPU + 20 RDMA regs (skipped 0 broadcast)" per task:
- **RUN A geom_all=0:** conv0 (task=0) distinct=240, dw1 (task=1) distinct=1. Baseline.
- **RUN B geom_all=1:** conv0 distinct=**1** (min=fe max=fe = uniform 0xfe -- geom_all's out-of-sequence
  DPU/RDMA writes wrecked conv0's compute), dw1 (task=1) distinct=**1** (unchanged).
- **Verdict:** CPU-forcing the ENTIRE regcmd config (CNA/CORE/DPU/RDMA, every block) does NOT make the
  chained layer compute, and it corrupts conv0 -- so the CPU writes reach the executer, yet no register
  value is the miss. **The chained-layer CMAC arm is NOT any regcmd register. The regcmd-register line is
  CLOSED.**
- **Where this leaves the three exclusions:** (1) not CBUF data (dw1's data reaches the CBUF); (2) not any
  regcmd register (CNA/CORE/DPU/RDMA all CPU-forced, dw1 still 0); (3) => the differentiator between conv0
  (cold-start) and dw1 (chained) is a **cold-start internal hardware CONTEXT** established only for the
  first task after NPU (re)init, not reproducible by any register write.
- **NEXT:** the remaining routes are structural, not register-level. (a) per-layer true cold-start (full
  NPU re-init/reset between layers) -- a minefield (rekick_reset=2 crashed, soft_reset irrelevant,
  force_powercycle hangs); (b) read the RK3588 open-rocket chained path (Tomeu's RK3588 runs int8
  MobileNet byte-correct, so its task 2+ DO compute) and find the one RK3576 delta -- the "adapt not RE"
  route, likely the most tractable.

## 2026-07-04 (CBUF audit_all pins the break at CBUF->CMAC, NOT CNA->CBUF. dw1's real data DOES reach the CBUF (6 windows changed PRE->POST, nz 714->1023) yet the CMAC outputs zero -> NBUF is RULED OUT, the break is downstream of CBUF staging. CBUF_CON live=0x44 identical for conv0 and dw1; the CNA rawor CSC bit is 0 for BOTH so it does not pin CSC.)

Board, seq-kick + warm-chain, rocket.audit_all=1 (per-task 16x64KB CBUF windows PRE/POST + changed-window
diff + CBUF_CON live/regcmd decode, kernel branch rk3576-cbuf-audit-alljobs 47b58df1d). Per-task snapshots
labelled by DPU-out iova (conv0=0xfeb2d000, dw1=0xfea69000):
- **dw1's data reaches the CBUF.** dw1 PRE (= conv0's leftover, 242/714 ...) -> POST 188/1023 192/1022 ...,
  POST changed[0x00000 0x10000 0x20000 0x30000 0x40000 0x50000] = SIX windows changed, nonzero rose
  ~714->~1023 (dense real data staged). conv0 stages too (changed[0x0..0x40000], 5 windows). **Both layers
  stage into CBUF; only conv0's is consumed by the CMAC. So CNA->CBUF is NOT the break -> NBUF RULED OUT
  -> the break is CBUF->CSC->CMAC (data present, not consumed).**
- **CBUF_CON does not differentiate.** live=0x00000044 for BOTH conv0 and dw1 (DBANK=4, WBANK=4) while the
  regcmd requests DBANK=0 for both (conv0 CON0=0x10000000, dw1 CON0=0x14000000; low 14 bits 0 both) -> the
  executer runs a default bank config the regcmd never latches (same PP-latch as geom_both), identical
  across layers. DATA_ENTRIES differ (conv0=15, dw1=56) as expected per layer size.
- **CORRECTION / caveat:** the CNA rawor CSC bit is 0 for conv0 (which COMPUTES) as well as dw1, so
  "CSC never fired" is NOT supported by rawor -- it does not pin the break. (conv0 rawor=0x30000000,
  dw1=0x20000008; the decoded FEAT/WT/CSC bits 0-5 are ~0 for both; dw1 has WT1=1, conv0 WT=0, which is
  the opposite of a "dw1 didn't load" story.)
- **NEXT:** the break is CBUF->CMAC. If the 64KB windows == the 16 CBUF banks, DBANK=4 => the CMAC reads
  bank 4 (window 0x40000), which BOTH layers changed -- so pin the exact bytes/offset the CMAC reads per
  (DBANK=4, DATA_ENTRIES): does dw1's staged data actually occupy the sub-range the CMAC walks, or does
  dw1's DENTRIES=56 layout leave the CMAC's read window empty? i.e. match "where the CNA wrote" against
  "where the CMAC reads" for dw1 vs conv0.

## 2026-07-04 (geom_both REFUTED as the dw1 miss — config-latch is NOT it. dw1 still distinct=1 with its config CPU-forced into both PP-groups, and conv0 even DEGRADED 239->111 (proving the CPU writes DO reach the executer). The wall is confirmed to be CNA->CBUF->CMAC data staging, not register geometry.)

Board A/B, seq-kick + warm-chain (the regime where dw1 reads dt_rd=20384), all-tasks readback. geom_both
fired (logged "wrote 96 CNA/CORE regs into both groups" per task):
- **RUN A geom_both=0:** task=0 (conv0) distinct=239, task=1 (dw1) distinct=1. Baseline wall.
- **RUN B geom_both=1:** task=0 distinct=**111** (still a real map, min00 maxff, but fewer values —
  geom_both's double-write perturbed conv0), task=1 (dw1) distinct=**1** (unchanged).
- **Verdict:** forcing dw1's real CNA/CORE config into BOTH ping-pong groups did NOT make dw1 compute,
  and it measurably CHANGED conv0's output (239->111) — so the CPU writes genuinely reach the executer
  (the config-latch premise holds), yet dw1 still MACs zero with its config present. **Config geometry is
  definitively NOT the dw1 miss.** dw1 reads its input (dt_rd=20384) and its weights (wt_rd=36); the only
  stage between the CNA DMA and the CMAC is the CBUF. So the break is CNA->CBUF (data DMA'd but not landed
  in the CBUF bank the CMAC reads) or CBUF->CSC->CMAC (data in CBUF but the CSC never reads it) — and only
  the cold-start task clears it. cbuf_reset knobs already DEAD.
- **NEXT (i):** diagnostic — dump conv0 vs dw1 CNA CBUF-config registers (cbuf entry/bank alloc) + any
  CSC/CMAC status, to pin the break at CNA->CBUF vs CBUF->CMAC before touching the big NBUF structural
  route (ii).

## 2026-07-04 (STAGE 2 — vendor rknpu init audit. RK3576 has two SoC-unique inits: (1) rk3576_state_init = CNA ping-pong dual-group prime (rocket DOES replicate as pp_state_init); (2) rk3576_cache_sgt_init + NBUF on-chip SRAM operand cache (rocket/mesa NEVER replicate). The diagnosed mechanism: the CMAC executer reads config from the CNA PP-groups; regcmd/PC writes don't reliably latch, only CPU writes do; geom_both ruled out config-geometry, leaving CNA->CBUF->CMAC data staging as the cold-start-only step. NEXT cheap shot: geom_both=1 in the new dw1-reads-input regime, never tested there.)

Audited `rk3576-vendor-kernel/drivers/rknpu` init + commit path against rocket.

**Vendor commit_pc (rknpu_job.c:448-720) is ONE submit; the PC hardware iterates task_number tasks.**
Per submit it writes: 0x10 PC_DATA_ADDR=first_task->regcmd_addr; 0x14 PC_DATA_AMOUNT; 0x20 INT_MASK;
0x30 PC_TASK_CON=((0x6|task_pp_en)<<bits)|task_number; **0x34 PC_DMA_BASE_ADDR=args->task_base_addr**
(rocket writes 0x34 = 0 — but conv0 computes with 0x34=0, so not the arming); 0x08 OP_EN 1 then 0. No
per-task software re-arm — the units are re-programmed from each task's regcmd as the PC strides.

**RK3576-unique inits (state_init/cache_sgt_init are non-NULL ONLY for rk3576; NULL for 356x/3588/etc):**
1. `rk3576_state_init` (drv.c:111): `0x10=1; 0x1004=0; 0x1024=0x80000000; 0x1004=1; 0x1024=0x80000000;
   0x1004=0x1e` = prime BOTH CNA ping-pong groups with the default DS1=0x80000000, leave POINTER=0x1e
   (PP_MODE|EXECUTER_PP_EN|PP_EN|PP_CLEAR). **rocket replicates this byte-for-byte in
   rocket_core_pp_state_init** — but rocket RE-RUNS it at the head of every job; the vendor runs it ONCE
   at probe / after reset.
2. `rk3576_cache_sgt_init` (drv.c:123) + NBUF: builds cache_sgt describing NBUF SRAM blocks
   (0x3fe80000, 1MB, 448/64/448/64 KB). rknpu_gem.c maps a BO flagged RKNPU_MEM_TRY_ALLOC_NBUF /
   RKNPU_CACHE_NBUF so its first nbuf_size bytes land in on-chip SRAM instead of DRAM (map_with_cache_sgt
   @422). **rocket/mesa never allocate a cache BO → the whole graph runs from DRAM.** Biggest structural
   gap, but conv0 (DRAM input) computing shows DRAM is not a hard requirement; NBUF-dependence of chained
   layers is unproven.

**Mechanism (from rocket's own accumulated comments, now joined to today's dw1-reads fact):** the CMAC
executer reads its CNA/CORE geometry from the active ping-pong group. regcmd writes driven by the PC do
NOT reliably latch to the group (both groups read back the pp_state_init default DS1=0x80000000); only
CPU writes latch. `geom_both` (CPU-replicate the regcmd's CNA/CORE config into both groups) was tried and
"ruled out the register geometry" — so the config VALUES are not the miss; the diagnosed racy part is the
**CNA->CBUF->CMAC data staging** (a warm/non-first task's CBUF holds stale/empty data). cbuf_reset knobs
= DEAD. This matches the cold-start wall: staging only works for the first task after a fresh
pp_state_init/CBUF; later tasks read their input (dt_rd=20384, new today) but the CBUF->CMAC step is empty.

**NEXT (cheap, no kernel rebuild — geom_both is already compiled in):** set rocket.geom_both=1 in the
CURRENT seq-kick/warm-chain regime and read dw1 (task=1) output. geom_both was only ever tested back when
dw1 didn't even read its input (config was moot then); with dw1 now reading real input, forcing its config
into the PP group is a fresh test. dw1 distinct>1 => config-latch was the miss; dw1 still 1 => confirmed
CBUF data-staging, pivot to CBUF/NBUF structural.

## 2026-07-04 (COHERENCY RULED OUT from existing logs — dw1's input probe reads conv0's REAL 244; no flash needed. The intermediate is NOT clobbered with zeros; dw1 reads real data and still MACs to zero. Wall = cold-start CMAC-arm, data-independent.)

The NPU-intermediate cache-coherency/clobber hypothesis (dirty CPU zero-lines on the producer-output ==
consumer-input BO get written back after the producer's NPU write, so the consumer reads zeros) is
DISPROVEN by the all-tasks readback already on disk — no new build/flash required:
- dw1's `in ` probe iova == conv0's `out` iova == `0xfeb2d000` (the SAME physical BO; producer output
  IS consumer input). It reads **distinct=242 (RUN3, chain) / 244 (RUN1, seq-kick), min=00 max=ff** — a
  full real feature map. The readback path is `dma_sync_for_cpu` (invalidate) → read DRAM, so 244 means
  **DRAM genuinely holds conv0's real output**; a zero-clobber would have made it read 0.
- Nothing writes `0xfeb2d000` between conv0 (task 0) and dw1 (task 1), so at dw1's read time it was 244.
  **dw1 reads dt_rd=20384 of REAL input and still writes all-zero (distinct=1).**
- A `dma_sync_for_device`-all-BOs flush would clean CPU→DRAM, but the input DRAM is already real — there
  is nothing to clean that changes dw1's read. The flush test is predicted to be a no-op and was NOT
  built (would cost a flash to confirm what the log already shows).

So the discriminating variable is NOT input content (it is real) — it is task POSITION / cold-start:
conv0 and a standalone dw (first/only task) compute; dw1 (a later task) reads the same real bytes and
does not MAC. **Wall = only the cold-start task after NPU-init arms the CMAC; data-independent.** Next
lever is Stage-2 (rknpu init path / what one-time state the first task consumes), NOT coherency.

## 2026-07-04 (DIAGNOSTIC GAP CLOSED — the "empty MAC" verdict was a MEASUREMENT ARTIFACT. The all-tasks readback shows conv0 does a REAL MAC (distinct=242/244, full 0x00–0xff) in EVERY dispatch mode, including the task_number=N chain. conv0 is EXONERATED. The sole remaining wall: every layer AFTER conv0 reads its input but its CMAC never fires — only the cold-start/external-input layer computes.)

Board test of the all-tasks readback (kernel branch rk3576-readback-alltasks, fe66cfa59: the post-completion
readback now loops over ALL `j->task_count` tasks and labels each `out` line with the real task index, instead
of only dumping `next_task_idx-1` = the last, never-run task). Same 3-run harness (RUN1 baseline seq-kick /
RUN2 nextptr+task_number=1 / RUN3 nextptr+task_number=N).

- **conv0's MAC is REAL, everywhere.** task=0 output-BO distinct histogram across all runs: `239 ×1, 242 ×6,
  244 ×12` (min=00 max=ff = a full feature map). The only `distinct=1` task=0 lines (×6) are a *different*
  single-task tail job's task 0, not conv0. **conv0 computes a real map even in the task_number=N chain (RUN3:
  `task=0 0xfeb2d000 distinct=242`).** The earlier "conv0 commits (dt_wr=25088) but the MAC is empty
  (distinct=1)" was read off the WRONG BO (task 28, the never-run last task). **conv0 / requant / conv0 weight
  layout are all EXONERATED — that path is correct and done.**
- **No layer after conv0 ever does a real MAC.** In the task_number=N chain (RUN3) every task=1..28 is
  `distinct=1 min=00 max=00` (dw1 at 0xfea69000 reads its input — dt_rd=20384 — but writes all-zero). In RUN2
  (task_number=1) likewise nothing past conv0. The ONLY non-cold `distinct>1` lines are in RUN1 (seq-kick) and
  are FALSE signals: `task=2 distinct=2` = values {00,80} = DPU wrote the requant zero-point, MAC contributed
  nothing; `task=3 distinct=3` = bytes `7f 80 7f 7f 0d 80 7f 80` **byte-identical across 8 inferences** =
  stale/constant, not a fresh MAC. Nothing past conv0 produces a real feature map in any mode.
- **The wall, now confirmed on the RIGHT BO:** only the cold-start / external-input layer (conv0) does a real
  MAC; every chained layer reads its input yet its CMAC never fires. This is exactly the "only the COLD-START
  task does MACs" wall from the topic file — previously inferred, now DIRECTLY measured.
- **Direction change.** Stop investigating conv0/requant/weight-layout (correct + done). The entire remaining
  problem is the chained (non-cold) layer's CMAC. Prime suspect stands: dw1 reads conv0's real `0xfeb2d000`
  (known distinct=242) but outputs zero — either "only the first task the PC executes arms the CMAC", or an
  NPU-write→NPU-read visibility gap. In seq-kick, conv0/dw1 are separate jobs, so dw1's `in ` probe reads
  `0xfeb2d000` directly — NEXT: check whether dw1's `in ` shows the real 242 or 0/stale.

## 2026-07-04 (task_number=1 REFUTED — the RK3576 PC follows the trailer only at task_number=N, not =1 (opposite of RK3588). AND a diagnostic gap surfaced: the continuous-mode readback dumps the LAST task (28), never conv0, so the "empty MAC" premise is UNCONFIRMED — conv0's actual output in a chained submit has never been seen.)

Board test of `rocket.chain_task_number=1` (override PC_TASK_CON task_number field to 1 while the trailer stays;
kernel branch rk3576-chain-tn1, d168a289a). RUN 2 (task_number=1) vs RUN 3 (task_number=N contrast):
- **task_number=1 does NOT chain.** RUN 2: `TASK_CON=0x00010001` (field=1, override confirmed), but `top dt_rd`
  peaked at 9408 — only conv0's operands loaded, the PC ran ONE task and stopped, no trailer follow. RUN 3
  (field=N) reproduced dt_rd=29792 (conv0+dw1, one hop). **So the RK3576 PC follows the trailer only in
  task_number=N mode; at task_number=1 it runs a single task — the OPPOSITE of upstream RK3588 (task_number=1 +
  trailer chains).** The task's premise (port RK3588's task_number=1 + trailer) does not hold on RK3576. So
  trailer-follow (needs task_number=N) and single-task committing mode (task_number=1) are mutually exclusive
  here.
- **Diagnostic gap — the "empty MAC" premise is UNCONFIRMED.** The whole-graph readback dumps the BOs of task
  `next_task_idx-1` = 28 (the LAST task, which never runs) — e.g. RUN 2's only output readback is
  `out task=28 iova=0xfe250000 distinct=1`. **conv0's own output BO has NEVER been read back in a chained
  submit.** So the earlier "conv0 commits (dt_wr=25088) but the MAC is empty (distinct=1)" was inferred from the
  WRONG BO (task 28, or a mislabeled task=0 iova). conv0's real MAC quality in a task_number=N chain is unknown.
  If conv0 actually computes real there and merely fails to advance past dw1, the problem is ADVANCE, not MAC —
  a completely different shape. NEXT (must do before more levers): fix the readback to dump the FIRST task's
  (conv0's) output BO in continuous mode, and settle real-vs-empty definitively.

## 2026-07-04 (PARTIAL BREAKTHROUGH — the RK3576 PC DOES follow next-pointers. A task_number=N submit advanced past conv0 for the first time: the PC chained conv0→dw1 and loaded dw1's operands. This overturns the "iteration only / silicon wall" conclusion. The empty-MAC wall persists though, and the chain stalls after one hop.)

Board test of the next-pointer build (ROCKET_NEXTPTR trailer + wg_continuous task_number=29), RUN 2 vs the
baseline seq-kick RUN 1:
- **The PC followed the trailer.** RUN 2's first job: `top dt_rd=29792 wt_rd=132`. From the baseline, conv0 =
  dt_rd 9408 / wt_rd 96 and dw1 = dt_rd 20384 / wt_rd 36. **9408+20384 = 29792 and 96+36 = 132, exactly** — so
  the PC loaded conv0's operands AND dw1's operands in one submit. Before the trailer (Fork A EXP-1), the same
  task_number=N submit loaded only conv0 (dt_rd=9408). **So the RK3576 PC does follow next-pointers — the first
  time a multi-task submit ever advanced past conv0.** This contradicts the earlier "the PC only auto-strides,
  the wall is silicon" conclusion.
- **conv0 now commits.** core dt_wr went 0 → 25088 (before the trailer, task 0 of task_number=N never committed).
- **But two walls remain.** (1) The output is degenerate (distinct=1): conv0 wrote 25088 bytes but the MAC was
  empty (bias→relu→zp), the same task_number≥2 empty-MAC. (2) The chain stalled after one hop — dt_rd never
  exceeded 29792 (task 2 / pw1's 5152 never loaded), TASK_STATUS stuck 0/29; dw1 loaded its operands but never
  committed, so the PC stalled at dw1.

**This reopens everything.** The multi-task wall was never "the PC can't chain" — it CAN (conv0→dw1 proven).
The remaining wall is the empty MAC in task_number≥2 mode: even task 0 computes nothing when task_number=29,
though it commits and advances. The natural next lever falls straight out of it: run each task in the committing
(task_number=1) mode while the trailer does the advancing — i.e. dispatch task_number=1 + the next-pointer
trailer, so the PC follows the chain but each task runs in the mode that does real MACs. NEXT: task_number=1 +
trailer (a kernel knob to submit task_number=1 with the chained regcmd).

## 2026-07-04 (The next-pointer path is the ONE untried PC mechanism and is worth trying — correcting my earlier over-hasty dismissal. It is RK3588's tile-chaining, not a whole-graph or a vendor-RK3576 mechanism, so this is a NOVEL cross-op construction and a gamble on whether the RK3576 PC follows next-pointers — but it is a DIFFERENT PC code path than the walled iteration, and it could keep each task in the committing (task_number=1-like) mode while the trailer advances.)

Woo relayed a task to route RK3576 through RK3588's embedded next-pointer chaining. Read the code to judge it:
- **The trailer is two PC registers.** RK3588's `rkt_fill_regcmd` ends each task with `EMIT(REG_PC_BASE_ADDRESS,
  0)` + `EMIT(REG_PC_REGISTER_AMOUNTS, 0)` (rkt_regcmd.c:1283-1285); `compile_operation` patches them with the
  next task's address/count (`|= next_addr<<16`, rkt_ml.c:293-306), guarded `soc != RK3576`. REG_PC_BASE_ADDRESS
  = 0x10 = RK3576's PC_DATA_ADDR, so the trailer registers exist on RK3576 — mechanically portable.
- **But the next-pointer chains TILES within one operation** (compile_operation loops `operation->tasks`), not
  layers across the graph. On RK3588 the whole graph is **per-op jobs** (one DRM job per layer); cross-layer is
  DRAM. MobileNet's mostly-single-tile layers (num_tasks=1) emit NO trailer, so next-pointers are not even what
  makes RK3588's MobileNet work.
- **The vendor RK3576 works via task_number=N iteration with NO trailer.** So next-pointers are NOT "the missing
  RK3576 piece the vendor has" — the vendor doesn't use them. This corrects the task's framing.

**Corrected judgment (my earlier FINDINGS dismissal "next-pointer is not the RK3576 mechanism" was a
non-sequitur — the vendor choosing iteration doesn't preclude the RK3576 PC also following next-pointers).**
Worth trying, because: (1) our only tried multi-task path (task_number=N iteration) walls, byte-identical to the
vendor yet failing — an unresolved paradox; (2) the next-pointer is a DIFFERENT PC code path the audit never
touched; (3) if the whole graph is chained task-by-task via trailers with each task run in the committing
(task_number=1-like) mode and the PC advancing on the trailer, it could sidestep the task_number≥2 commit gate
entirely. Honest unknown: the vendor doesn't use next-pointers on RK3576, so whether the RK3576 PC follows them
is the experiment — if it does, later tasks compute (dt_wr>0, distinct>1); if not, the chain stops after task 0.
Implementation is NOT a direct RK3588 port (that's per-op tile chaining) but a novel cross-op construction: emit
the trailer in the RK3576 fills + patch next-pointers across the whole packed graph + dispatch so the PC walks
the chain. Cheap (build; Woo flashes), resolves the question either way. Branches rk3576-nextpointer (mesa+kernel).

## 2026-07-04 (Audit COMPLETE — the completion path, perf counters, and clock/power/iommu are clean too. Every software path is byte-identical/equivalent to the vendor. No software bug anywhere in the audited surface; the multi-task wall is definitively the PC's internal task_number≥2 behavior.)

Finished the audit — the completion/finalize path and the environment:
- **Completion + finalize are correct.** poll_timer_fn (multitask) waits PC_TASK_STATUS==task_count with a
  500ms cap, then schedule_work → handle_irq → finalize; finalize re-kicks while next_task_idx < task_count and
  signals the fence + puts pm_runtime when all tasks are consumed (rocket_job.c:2136-2144). Correct.
- **Perf-counter offsets are correct.** Vendor rknpu_top_amount = 0x2210/0x2234/0x2238/0x223c and
  rknpu_core_amount = 0x2410/0x2434/0x2438/0x243c; ours read 0x210/0x234/… (top) and 0x410/0x434/… (core) from
  stats_iomem, i.e. our stats_iomem base is the vendor's core+0x2000 — the offsets match. And single-task reads
  dt_wr=25088 correctly, so **dt_wr=0 in multi-task is a REAL zero, not a mis-read** (corroborated by output
  distinct=1).
- **Clock/power/iommu are not task_number-specific.** Single-task commits in the exact same environment (same
  clocks/PVTPLL, same power domain, same attached domain), so none of these can gate a task_number≥2-only
  failure.

**AUDIT CONCLUSION (thorough).** Everything the software controls is byte-identical or equivalent to the vendor
across every path: the packed regcmd bytes (part 2), the submit register sequence (part 1), the requant, the
S_POINTER, the completion, the perf offsets, state_init/arm/pulse, and no 0xf008 either side. There is **no
software bug in the audited surface.** The multi-task wall — task_number≥2: task 0 loads its operands (dt_rd>0)
but the CACC never commits (dt_wr=0, output distinct=1) and PC_DONE asserts instantly (samples=1), while
task_number=1 with the identical stream commits (dt_wr=25088) — is the **PC task-sequencer's internal behavior
for task_number≥2**, below the software surface. That is the definitive, audited answer to a month of walls.

## 2026-07-04 (Audit part 2 — the per-layer regcmd is CLEAN too: requant/OUT_CVT is validated and the model is per-tensor; the S_POINTER value matches the vendor and the mesa comment's own "0x0e desyncs multi-task" theory is REFUTED by the vendor using 0x0e as well.)

Continued the audit into the mesa per-layer regcmd generation (rkt_regcmd.c fill_regcmd_rk3576_normal):
- **Requant / OUT_CVT is validated.** `conv_scale = in_scale*wt_scale/out_scale → cvt_scale (15-bit) + shift`
  (rkt_regcmd.c:352-360). This is the same math proven byte-exact on conv2d-cal, and mobilenet_v1_1.0_224_quant
  is per-tensor (single weights_scale), so a scalar requant is correct. offset = output_zp - 0x80. Not a bug.
- **S_POINTER value matches the vendor.** mesa's default per-task `sptr = 0x0e` (ROCKET_SPTR, rkt_regcmd.c:400):
  POINTER=0 | PP_EN | EXECUTER_PP_EN | PP_MODE(1). The mesa comment (380-397) theorises that PP_MODE=1
  auto-alternates the ping-pong group and DESYNCS on a multi-task graph → geometry lands in a group the executer
  never reads → "units engage but the DPU writes nothing" (= the dt_wr=0 symptom). BUT the vendor's own dw
  regcmd entry[0] is `reg=1004 val=0x0e` — the vendor uses the SAME 0x0e (PP_MODE=1) and its multi-task works.
  So the desync theory is REFUTED and 0x0e is not the bug.

So both the submit path (part 1) and the per-layer regcmd (part 2) are clean and vendor-matching. Everything the
software controls — the packed bytes and the submit register sequence — is byte-identical to the vendor across
every path audited. The remaining anomaly (vendor's bare pulse engages, ours needs the per-unit op_ens; and
task 0 never commits in task_number≥2 with a byte-identical stream) has no software cause left in the audited
surface. Still unaudited: the completion/finalize path and the clock/power/iommu environment (both unlikely to
gate a task_number-specific commit, since single-task commits in the same environment).

## 2026-07-04 (Audit part 1 — the kernel submit path + mesa whole-graph packing are CLEAN: they match the vendor. No second bug there. Reinforces that the multi-task wall is the PC's internal task_number≥2 behavior, not a submit bug. Still to audit: completion path, per-layer regcmd correctness, clock/power/iommu.)

Chewed through the kernel `rocket_job_hw_submit` and mesa `rkt_pack_graph_regcmd` line by line vs the vendor
`rknpu_job_subcore_commit_pc`:
- **The commit_pc 8-step sequence matches** (S_POINTER arm 0xe on CNA 0x1004 / CORE 0x3004 → PC_DATA_ADDR
  (0x10) → PC_DATA_AMOUNT → INT_MASK=last → INT_CLEAR=first → PC_TASK_CONTROL (0x30) → PC_DMA_BASE_ADDR →
  PC_OP_EN 1→0). Order and values match; RKNPU_OFFSET_PC_DATA_ADDR=0x10 == our BASE_ADDRESS.
- **`BASE_ADDRESS=0x1` (rocket_job.c:893) is harmless dead cruft** — PC_BASE_ADDRESS bit0 is PC_SEL (TRM-reserved);
  it's overwritten by the regcmd-addr write at :972, and the vendor also leaves PC_SEL=0 (regcmd_addr is aligned).
- **The vendor NEVER writes 0xf008 (ENABLE_MASK) anywhere** (only the macro + a struct field exist); its units
  engage from rk3576_state_init + the per-submit S_POINTER arm + the PC_OP_EN pulse — identical to ours.
- **rk3576_state_init == our rocket_core_pp_state_init** exactly (re-confirmed).
- **The whole-graph stride is NOT a bug.** mesa packs at a uniform `stride_amount = ((max_amount+5)/2)*2`
  (rkt_ml.c:140) and reports every task's amount as that uniform stride (all 522 kicks show DATA_AMOUNT=0x49 =
  143), so the kernel's PC_DATA_AMOUNT (from task[0]) equals the packing stride — the PC strides correctly and
  shorter tasks are zero-padded to the stride.

So the submit path is clean and vendor-matching. The one thing that still doesn't add up structurally: the
vendor's single PC_OP_EN pulse engages its units (no in-stream op_en, no 0xf008) while ours needs mesa's
injected per-unit op_ens to engage — with a byte-identical arm+pulse+state_init. That per-unit-op_en engage is
what loads the operands in continuous mode (dt_rd=9408) but the CACC still never commits (dt_wr=0). NOT YET
AUDITED (bugs may hide here): the completion/finalize path, the per-layer regcmd generation in mesa
(requant/OUT_CVT, feature/weight/bias addresses, DPU+RDMA config — correctness bugs that would bite the chain
once it runs), and the clock/power/iommu environment.

## 2026-07-04 (Reframe: the next-pointer angle is not the RK3576 mechanism [vendor uses pure task_number iteration, which WORKS for the vendor], so the wall is not the bytes or the mechanism — it is OUR rocket driver's task_number=N execution environment. Even the vendor's exact bytes replayed through our driver wall in ONEJOB mode. Next: a thorough audit of the driver's whole submit→completion path.)

Checked the RK3588 self-chain next-pointer path (rkt_ml.c:282, guarded soc!=RK3576) as the last "adapt working
code" lever. The vendor RK3576 dw regcmd (vendor_dw_regcmd.txt) ends in real unit registers (RDMA 0x507c) with
NO PC/next-pointer entries — so RK3576 uses pure **task_number iteration** (the PC auto-strides the packed
regcmd array), not RK3588's embedded next-pointers. And **the vendor's iteration WORKS** (its whole graph
computes). So the mechanism isn't broken and next-pointers aren't the RK3576 path.

That reframes the wall precisely: **the vendor's task_number=N iteration works; ours walls — with byte-identical
regcmd AND byte-identical submit registers. And the vendor's own captured bytes, replayed through our rocket
driver, ALSO wall in ONEJOB (task_number=N) mode while SPREAD (N jobs) computes conv0.** So the wall is not in
mesa and not in the command stream — it is in **our rocket driver's task_number=N execution environment** (the
clocks/PVTPLL, genpd power, rk_iommu, soft-reset, PC write ordering — everything the driver sets up around the
byte-identical submit). Precedent: the VoidChecksum RK3576 rocket series needed extra kernel fixes (SError /
IOMMU / CBUF-zero, forks 0002/0005/0009/0010) just to run on real HW, so the multi-task wall is plausibly
another driver-environment hole, not microcode. NEXT: audit the driver's whole submit→completion path against
the vendor rknpu_job_subcore_commit_pc, looking for MORE than one gap (clock/power/reset/iommu/PC-ordering).

## 2026-07-04 (The IRQ-completion lever is DEAD on inspection — the wall is now pinned to one screw: in task_number≥2 mode the PC asserts PC_DONE instantly [samples=1] without ever driving the DPU [dt_wr=0], while task_number=1 drives it [dt_wr=25088]. Pure internal PC-sequencer behavior; no driver lever reaches it.)

Inspected the IRQ-completion lever (the one Fork A path never tried) before building it — and it is already
effectively present and does not touch the gate:
- **The IRQ path is already wired.** `rocket_job_irq_handler` (rocket_job.c:2222) already fires on
  INTERRUPT_RAW_STATUS bits 0-13 (which include 0x300 = the DPU-done bits), clears them, and wakes the thread →
  the same completion handler the poll uses. So "switch to IRQ completion" changes nothing structural.
- **int_mask already == the vendor's 0x300** (confirmed from the capture). No difference.
- **The PC advances tasks internally.** The vendor enables only the LAST task's int_mask and waits for that one
  IRQ; it does not service per-task interrupts. So the task-to-task advance is the PC's own hardware, not
  driver-serviced — poll-vs-IRQ cannot change it.
- **The "in-execution polling perturbs the DPU" confound is also dead.** In continuous mode the cnalive sample
  loop showed `samples=1` — it broke after ONE read because PC_DONE was already set. So there was no heavy
  in-execution polling to perturb anything.

That last point exposes the wall's true shape: **in task_number≥2 mode the PC asserts PC_DONE immediately
(samples=1) and task 0's DPU never writes (dt_wr=0); in task_number=1 mode the PC drives the DPU to completion
(dt_wr=25088).** The only register that differs between the two is the task_number field of PC_TASK_CONTROL
(1 vs N) — everything else (int_mask, op_en, S_POINTER arm, state_init, the whole regcmd) is byte-identical to
the vendor. So the gate is the **PC task-sequencer's internal behavior for task_number≥2**, below the register
surface, unreachable from the driver.

**Software levers exhausted.** Ruled out, each with board or offline evidence: dispatch model (sequential kicks
vs continuous vs SPREAD), per-kick teardown (bisect 0xf), resume soft-reset, reset-per-layer (crashes), regcmd
bytes (byte-identical to the vendor), input data + coherency (dw1 reads conv0's real output), pw/dw/weight-fetch
(red herrings), op_en value, ENABLE_MASK-at-submit, cache_sgt/NBUF (vendor chains via DRAM), IRQ completion.
The wall is RK3576-specific PC microcode; RK3588's open stack works because it self-chains via embedded
next-pointers (rkt_ml.c:282, guarded soc!=RK3576) — the untried RK3576 analogue.

## 2026-07-04 (Lead A [cache_sgt/NBUF] is a DEAD END — verified: the vendor chains layers through a 2 MB DRAM intermediate, not NBUF. So the sole mechanism that makes chained layers compute is the continuous PC submit, which walls for us. Next: the one untried Fork A lever — IRQ-driven completion + per-task int_mask instead of PC_DONE polling.)

Before building the (large) cache_sgt machinery, checked whether the vendor actually puts intermediates on-chip.
The vendor MobileNet capture (dirty/rknpu_replay/meta.txt): `bo idx=2 dma=0xffde1000 size=2158592` — the
intermediate activation buffer is **2.06 MB, DRAM-backed** (a normal 0xffde1000 IOVA), which cannot fit in the
1 MB NBUF; no BO in the capture is NBUF/cache-backed. So **the vendor chains layers through DRAM exactly as we
do; cache_sgt/NBUF is orthogonal to the chained-layer-MAC wall.** Lead A is dead. The vendor's chained layers
compute purely because of the **continuous PC submit** (one job, task_number=24, the PC managing the CBUF
pipeline task-to-task) — the operand location (DRAM) is identical to ours. And the continuous submit is exactly
what walls for us (Fork A: task_number≥2 → task 0's CACC never commits, PC wedges). So **"chained layers don't
MAC" and "continuous submit walls" are one wall: the PC-managed CBUF pipeline of the continuous submit.**

The one Fork A lever never tried: the vendor completes by **interrupt** — it enables the per-task int_mask
(0x300 = the DPU-done bits) in INTERRUPT_MASK and waits on int_status; our driver polls PC_DONE (bits 28/29,
which are read-only in INTERRUPT_MASK on RK3576) with an hrtimer and never services a per-task IRQ. If the PC's
task-to-task advance is gated on the per-task DPU-done interrupt being raised/serviced, then polling PC_DONE
without servicing that interrupt would stall the PC after task 0 — which is exactly the wedge we see. NEXT:
implement the vendor's IRQ-driven completion (per-task int_mask, service the NPU IRQ, advance on int_status) and
re-test the continuous submit.

## 2026-07-04 (Fork B — the resume soft-reset is NOT the MAC-enabler [REFUTED], the reset-per-layer fix CRASHES, and a self-check debunks the "bytes-vs-context" pivot: the "vendor dw computes" evidence was an EXTERNAL-INPUT dw, not a chained layer. No chained/later layer has ever computed on this open stack, in any dispatch mode.)

Two board runs + one offline self-check, all pointing the same way:

**(1) The resume soft-reset hypothesis, REFUTED.** The runtime_resume callback runs a full NPU soft-reset
(rocket_core_reset) and its comment claims "without the CBUF reset ... the CMAC reads zero out of an
uninitialised CBUF." So I guessed the cold-start's reset is what enables its MACs. Board control
`rocket.soft_reset=0` (verified it took effect — log shows "soft_reset=0, skipping full NPU reset" on a real
resume): **conv0 still computes (distinct=241).** So the resume soft-reset is NOT the MAC-enabler; conv0 does
not need it. Hypothesis dead.

**(2) The reset-per-layer fix, CRASHES.** `rocket.rekick_reset=2` (detach IOMMU → rocket_core_reset →
re-attach, per re-kick) faulted: `rocket_gem_bo_free → iommu_unmap` NULL deref at cleanup, "recursive fault,
reboot needed" — my inline detach/re-attach corrupts the domain's iommu mapping state, so freeing BOs later
NULLs. A driver bug in the experiment, not a HW verdict; dw1 stayed distinct=1 anyway. (The mid-graph
detach/reset/re-attach domain is exactly what the prior cbuf_reset=2 / power-cycle attempts died in.)

**(3) Self-check — the "bytes-vs-context" pivot is SHAKY.** I'd concluded "it's context, not the regcmd bytes,
because the vendor's dw computes from byte-identical bytes." Re-reading how that was measured (replay_rocket.c
SPREAD = N single-task DRM jobs in one submit ioctl, one session): the "standalone dw112 computes" case is a
dw reading **external** DRAM input — it computes for the same reason conv0 does. The **chained** SPREAD replay
(conv0→dw1→pw1→dw2) showed conv0 compute and **every chained layer read nothing (dt_rd=0) and produced
nothing.** So there is NO evidence any chained/later layer has ever computed on this open stack, vendor bytes or
ours, in any dispatch mode. The honest statement: **the first/external-input layer always computes; a
chained/later layer never has.** The byte-diff (mesa dw regcmd == vendor dw regcmd) is still a fact; what's not
supported is the leap "therefore a comparable computing case exists, so it must be context."

**What this sharpens.** Our mesa sequential-kick dw1 is actually one step further than the SPREAD chain: warm-
chain makes it **read its input** (dt_rd=20384, from conv0's real output feb2d000 which holds distinct=239),
yet it still does no MAC. The only difference between the computing standalone-dw and the non-computing
chained-dw1 is external-input vs intermediate-input. **Prime suspect: does dw1's CNA actually read conv0's REAL
output, or stale/zero data?** dt_rd=20384 says it read 20384 bytes, not that the bytes were right — an
NPU-write-then-NPU-read producer/consumer coherency gap would give a warm-looking read of zeros → MAC on empty
→ degenerate. NEXT: before dw1's submit, dump the actual bytes of its input BO (feb2d000) — conv0's distinct=239
real data, or zeros? Real data → it genuinely is "later layers don't MAC" (HW state); zeros → a coherency bug,
tractable.

**Coherency REFUTED (from the existing log, no board cycle).** The driver's own input readback already answers
it: `buf[3] in task=1 iova=0xfeb2d000 first=b8 7f 33 e5 80 7f 3d 7f ... distinct=237` — dw1's input BO holds
conv0's REAL output (distinct 237/241/240, matching conv0's output), correctly aliased (dw1-in iova == conv0-out
iova == feb2d000). The driver reads real data from feb2d000 between the kicks; dw1's CNA reads the same physical
via the same IOMMU — so dw1 reads its real input and still does no MAC. Not stale, not zero. So the wall is now
as tight as software can make it: a layer reading EXTERNAL (CPU-provided) input computes; a layer reading an
INTERMEDIATE (NPU-produced, real, correctly-addressed, byte-identical regcmd) input does not, in every dispatch
mode. Ruled out: regcmd bytes, teardown, resume soft-reset, input data, coherency, dispatch mode. The one thing
left that differs between conv0 and dw1 is the on-chip CBUF/CMAC STATE conv0 leaves behind (independent of dw1's
DRAM input), which no software lever re-initialises without cooling the CBUF (warm-chain) or crashing (reset).
→ lead (A): the vendor's on-chip-buffer mechanism (cache_sgt/NBUF) + the PC-managed CBUF pipeline of the
continuous submit.

## 2026-07-04 (Fork B teardown bisect — the per-kick teardown is EXONERATED. Skipping ALL of it does not restore a re-kick's MACs. The MAC-enabler is the fresh-job context, not any between-kick software step.)

Added `rocket.bisect` (bitmask) to disable each per-kick teardown step and measured the true dw1 output
(iova 0xfea69000; the task-index labels in the buf readback are unreliable — a readback of conv0's bo was
mislabeled task=1 d=238, which is NOT dw1). One boot, sequential-kick mode, sweeping bisect:

| bisect | disables | conv0 (feb2d000) | dw1 (fea69000) |
|--------|----------|------------------|----------------|
| 0 baseline | — | 235 | **1** |
| 0xf | ALL teardown | 238 | **1** |
| 0x1 | sptr-toggle diag | **98** (worse) | 1 |
| 0x2 | sptr-rearm | 239 | 1 |
| 0x4 | int-clear-full | 238 | 1 |
| 0x8 | perf-clear | 236 | 1 |

**dw1 stays distinct=1 in every configuration, including 0xf (skip ALL teardown).** So none of the between-kick
software steps — the diagnostic S_POINTER 0→1 toggle, the driver S_POINTER re-arm, the full INTERRUPT_CLEAR, the
perf-counter clear — is the MAC-killer. **The per-kick teardown is exonerated; the original instinct is wrong.**
(Side note: skipping the diagnostic S_POINTER toggle, 0x1, made conv0 *worse* — 235→98 — so that toggle is
somehow helping the group state, not hurting it.)

So the discriminator is the **fresh-job context vs a re-kick**, not any register we clear between kicks:
- the vendor's standalone dw112 replayed as 6 separate single-task **jobs** computes;
- our dw1 as a **re-kick within one job** does not — same input read (dt_rd=20384), byte-identical regcmd.

The only thing a job boundary does that a re-kick doesn't: `pm_runtime_get_sync` + drm_sched arbitration +
`dma_fence_signal` + `pm_runtime_put_autosuspend`. The leading hypothesis is that **`pm_runtime_get_sync` (the
per-job PM resume) re-inits some HW state that enables the MACs, and a re-kick — which skips it — runs on a
state the first task consumed.** NEXT: dispatch each layer as its own DRM job (fresh pm_runtime_get_sync per
layer) with the intermediates persisted in DRAM, and see whether dw1 then computes (distinct>10). If yes, the
fix is per-job dispatch (not re-kicks); if no, even a fresh job doesn't help and the enabler is narrower
(a genuine per-inference/reset state).

## 2026-07-04 (Fork B byte-diff — the mesa dw regcmd is byte-identical to the vendor's; the bytes are NOT why it produces zero. It is EXECUTION CONTEXT. Next: bisect the per-kick teardown.)

To settle bytes-vs-context: byte-diffed the live mesa dw1 regcmd (board dump_regcmd, 139 entries) against the
vendor's captured dw regcmd (vendor_dw_regcmd.txt run 0), register by register, all four targets:

| target | identical | differs |
|--------|-----------|---------|
| CNA (0201) | 42/44 | 0x1088 (feature addr), 0x1110 (weight addr) — absolute IOVA vs vendor offset, both functional |
| CORE (0801) | 5/5 | — |
| DPU (1001) | 64/68 | 0x4018 (output addr — addressing); 0x40ac/0x40b0/0x40b4 (requant offset/mul/shift) |
| RDMA (2001) | 19/21 | 0x5020, 0x5024 (bias addr — addressing) |

The ONLY non-address value differences are the DPU requant triplet 0x40ac/0x40b0/0x40b4. Effective scale:
mesa 0x4ace>>0x10 ≈ 0.29 vs vendor 0x60e9>>0x18 ≈ 0.0015 — a ~200× gap, so the vendor capture's dw is a
DIFFERENT layer/model (same shape, different quant scales), not a mesa bug. (An earlier pass wrongly reported
mesa "omits the DPU_RDMA" — that was a log-extraction truncation: the dw dump runs lines 1166–1440 and the RDMA
tail 0x500c–0x507c sits at 1420–1440; mesa DOES emit the full DPU_RDMA incl. bias 0x5020/0x5024.)

So: **the mesa dw regcmd is byte-identical to the vendor's (modulo addresses and a different-layer requant).
The regcmd bytes are NOT why mesa's dw produces zero** — and yet mesa's dw1 *reads its input* (dt_rd=20384),
has a correct regcmd, and still outputs distinct=1. **The MAC-suppression is EXECUTION CONTEXT, not the command
stream.** This validates the original instinct: the cold-start task 0 runs on fresh HW state and does MACs; task
1 runs on the state task 0 left — correct regcmd, input read — and the CMAC never fires. NEXT: bisect the
per-kick teardown (OP_EN 1→0 vs leave high; skip the S_POINTER re-arm; skip INT_CLEAR; skip the perf-counter
clear) to find which step, removed, lets task 1 compute (distinct>10) — that isolates the state the cold start
consumes and later tasks lack.

## 2026-07-04 (Fork B — THE UNIFICATION: only the cold-start task does MACs. Every subsequent task, whether a sequential re-kick or a multi-task PC iteration, engages and loads its operands but does NO MACs. dw/pw/weight-fetch are red herrings.)

Picked B (make the sequential model correct) and mapped the per-task output of the working sequential-kick run
(RUN 1, MobileNet whole-graph, 29 tasks). The output `distinct` (a proxy for "did it compute") is decisive:

| task | layer | 0x100c mode | exec_ever | wt_rd (top) | out distinct |
|------|-------|-------------|-----------|-------------|--------------|
| 0 | conv0 (COLD start) | 0x2000a006 firstconv | 0xf | 96 | **239 (computes)** |
| 1 | dw1 | 0x1 dw-mode | 0xf | 36 | 1 (degenerate) |
| 2 | pw1 | 0x0 standard | 0x0 | 0 | 2 |
| 3 | dw2 | 0x1 dw-mode | 0xf | 128 | 3 |
| 4 | pw2 | 0x0 standard | 0x0 | 0 | 4 |
| 5 | dw3 | 0x1 dw-mode | 0xf | 72 | 2 |
| 6.. | rest | | | 0 | 1 (chain goes quiet) |

**Only task 0 (the cold-start conv0) actually does MACs (distinct=239). Every task after it — depthwise AND
pointwise alike — produces a degenerate output (distinct 1–4), no matter that the dw's engage (exec_ever=0xf)
and fetch weights (wt_rd=36/128/72).** So the whole "pointwise doesn't fetch weights / standard-mode doesn't
engage" line is a **red herring**: the dw fetches weights and engages and STILL produces nothing; the pw's
exec_ever=0 and wt_rd=0 don't matter because even a fully-engaged weight-fetching dw computes nothing. **The
real split is cold-start vs everything-after, not dw vs pw.**

This UNIFIES the two walls into one:
- **Sequential model**: only the first kick (cold-start conv0) does MACs; every re-kick after it is degenerate.
- **Continuous model**: task 0 is the cold start yet its CACC never commits (dt_wr=0) — the multi-task commit
  gate sits ON TOP, so not even the cold start computes there.
- **Same root** (= the git-HEAD "single-task-vs-multi-task line is the whole remaining mystery"): the CMAC only
  fires on the FIRST task of a fresh HW context. Some state the cold start runs on is consumed/spoiled and not
  restored for later tasks. Our sequential kicks tear down between tasks (OP_EN 1→0 + S_POINTER re-arm +
  INT_CLEAR + perf-counter clear, even with warm-chain skipping pp_state_init); the vendor's continuous PC
  submit has NO teardown between tasks, so every layer runs in one warm context and computes. warm-chain earlier
  got the later layers to engage + DMA but NOT to do MACs — this is exactly why.

So B has no cheap pw-config win; B and A converge on one question: **how to make a non-cold-start task do MACs.**
NEXT (this session): find precisely which per-kick teardown step kills the MACs — bisect the between-kick
sequence (OP_EN 1→0 vs leave high; S_POINTER re-arm vs leave; INT_CLEAR; perf clear) to see which one, when
removed, lets task 1 compute (distinct>10). That isolates the state the cold start consumes.

## 2026-07-04 (Fork A experiment 2: op_en-value fork CLOSED; the multi-task submit is byte-identical to the vendor's, so the wall is not in the registers — the RK3576-specific piece rocket lacks is cache_sgt/NBUF-backed operands.)

Read the vendor rknpu driver end-to-end to find what a task_number=N submit does that we don't:
- **Vendor `rknpu_job_subcore_commit_pc` (rknpu_job.c:685-715): NO ENABLE_MASK (0xf008) write, NO in-stream
  op_en at all.** Just PC_DATA_ADDR, PC_DATA_AMOUNT, INT_MASK=last_task->int_mask, INT_CLEAR=first_task->
  int_mask, PC_TASK_CONTROL=((0x6|pp)<<16)|task_number, PC_DMA_BASE_ADDR, then one PC_OP_EN 1→0 pulse. Units
  engage from the per-submit S_POINTER arm (0x1004=0xe, 0x3004=0xe; rknpu_job.c:489-490) + the pulse.
- **The vendor capture (dirty/vendor.txt:1843) is byte-identical to ours**: `int_mask=0x300 first_int_mask=0x300
  task_con=0x70002 task_base_addr=0x0 pc_data_amount=71`. So our fixed INT_MASK=0x300 already matches (per-task
  int_mask ruled out), and the vendor's own multi-task submit is task_number=2 with the exact registers we write.
  **The multi-task wall is NOT in the submit register values.**
- **`rk3576_state_init` == our `rocket_core_pp_state_init` exactly** (BASE=0x1, S_POINTER 0→1→0x1e, DATA_SIZE1=
  0x80000000 into both groups). Ruled out.
- **`pc_dma_ctrl=1` (RK3576) just wraps the PC_DATA_ADDR write in irq_lock** — the register write is identical.
  No functional difference. Ruled out.
- **The ONE RK3576-specific mechanism rocket entirely lacks = `cache_sgt` (rknpu_gem.c:422
  rknpu_iommu_map_with_cache_sgt).** A BO allocated "with_cache" gets its OWN iova mapped to the on-chip NBUF
  SRAM physical (`nbuf_start=0x3fe80000`, 1 MB, in 448+64 KB blocks per core from `rk3576_cache_sgt_init`).
  This is the vendor's on-chip-buffer path — a per-BO alloc flag with a proper block layout, NOT the arbitrary
  driver remap Fork B tried (and it's why Fork B's iommu_map(0xfff00000) conflicted). mesa never allocates
  cache BOs, so our whole graph runs from DRAM.

op_en-value fork, board (wg_continuous=1, 3 runs): RUN 2 `ROCKET_UNIT_OPEN=0x1d` (per-unit op_en to CNA 0x1008/
CORE 0x3008/DPU 0x4008/RDMA 0x5008 with the FULL enable the broadcast uses, no PC 0x08 touch) and RUN 3
`=0x1` are **IDENTICAL**: conv0 top dt_rd=9408 wt_rd=96 (loads), core **dt_wr=0** (no commit), TASK_STATUS stuck
1/29. **So completion in task_number≥2 is NOT gated by the op_en value — the op_en engages the CNA DMA either
way, and the CACC never commits regardless.** Fork CLOSED: no op_en value/presence/target lever moves the
multi-task completion (broadcast wedges the PC, per-unit 0x1 and 0x1d both stall at 1/29, STRIP gives no DMA).
The completion gate is task_number≥2-intrinsic and carried by no register the stream writes.

**Two leads remain.** (A) **cache_sgt/NBUF on-chip operands** — the biggest untested RK3576-specific difference;
the multi-task PC pipeline may require on-chip (not DRAM) operands, which would also explain the original CBUF-
continuity / pw-weight-staging problem. Big: needs a cache-BO UABI + mesa allocating cache BOs + kernel
cache_sgt map. (B) **Abandon continuous submit as a wall** and pre-stage pw weights within the WORKING
sequential-kick model by a different route (the sequential model already carries engage + feature + dw weights;
only large pw weights need the pipeline). Decide direction before more board cycles.

## 2026-07-04 (Fork A experiment 1: engage × dispatch matrix) — the crux refined one layer: in task_number=N mode conv0 LOADS its operands byte-identically to the working single-task, but the CACC never commits (dt_wr=0) and the PC wedges. Engage and continuous-iteration are mutually exclusive in our mechanism.

Added `rocket.wg_continuous` (rocket_job.c): dispatch the whole job as ONE task_number=task_count PC submit
(vendor commit_pc), instead of N sequential single-task kicks. One board boot, three inferences differing only
in dispatch × op_en (all MobileNet whole-graph, task_count=29):

| RUN | dispatch | in-stream op_en | conv0 load (top) | conv0 commit (core dt_wr) | PC state |
|-----|----------|-----------------|------------------|---------------------------|----------|
| 1 | N sequential kicks | kept | dt_rd=9408 wt_rd=96 | **25088** | completes, output distinct=239 |
| 2 | continuous N=29 | kept | dt_rd=9408 wt_rd=96 | **0** | OP_EN stuck 1, PC_RAW bit16, TASK_STATUS never advances |
| 3 | continuous N=29 | STRIP_OPEN | dt_rd=**0** | 0 | units never engage, no DMA at all |

What this nails:
- **RUN 2 conv0 loads its input (dt_rd=9408) and weights (wt_rd=96) — the SAME counters as the working
  single-task RUN 1.** So the multi-task wall is NOT an operand/DMA-fetch problem; the operands are in.
- **Yet core/CACC dt_wr=0** (RUN 1 = 25088): the compute/write-back never commits. Same operands, same config;
  task_number=1 writes 25088, task_number≥2 writes nothing. This refines the old "engages but never completes
  its DPU write" — the DMA does run, only the CACC commit / done-handshake is gated.
- **The PC wedges**: OP_EN stuck at 1 + PC_RAW bit16 set. This is exactly the kernel-comment warning that the
  in-stream 0x1d op_en, firing mid-iteration, restarts/wedges the PC. (After the stall, mesa's later jobs come
  in with DATA_ADDR=0 and each stalls the 500ms cap — noise; the board recovered, RUN 3 ran clean.)
- **RUN 3 reverse-proof**: strip the in-stream op_en and conv0 does not even DMA (dt_rd=0). So the in-stream
  0x1d is what TRIGGERS the CNA feature/weight DMA in our path. It is required for engage AND it wedges the PC
  in multi-task mode.

So the dilemma is proven both ways: **engage (CNA-DMA trigger) needs the in-stream 0x1d op_en; continuous PC
iteration needs it absent (else the PC wedges, OP_EN stuck 1).** Mutually exclusive in our current mechanism.
The vendor decouples them by folding ENABLE_MASK (0xf008=0x1d) into the submit (no in-stream op_en at all), but
our CPU write of 0xf008=0x1d before OP_EN hangs (prior finding). **Next Fork A lever: replicate the vendor's
ENABLE_MASK-at-submit so the CNA engages without an in-stream op_en and without hanging — read the exact
ENABLE_MASK write/ordering in rknpu_job_subcore_commit_pc and find what our earlier hanging write was missing.**
(Correction to the prior entry's claim that STRIP_OPEN units engage from the S_POINTER arm + one pulse — RUN 3
disproves it for our 0x1 pulse: armed S_POINTER=0x0e + one pulse with no op_en → exec_ever=0, dt_rd=0.)

## 2026-07-04 (Fork A opened) — the vendor's rknpu driver gives the exact continuous-submit recipe; the "1/29 stuck" crux is now precise: a task completes as task_number=1 but not as task 0 of a task_number=N submit.

Read the vendor rknpu kernel driver (rk3576-vendor-kernel/drivers/rknpu) instead of guessing at NVDLA RTL —
the PC iteration is Rockchip's, not NVDLA's, so the vendor driver is the real reference. `rknpu_job_subcore_
commit_pc` writes, in order: PC_DATA_ADDR = first_task->regcmd_addr; PC_DATA_AMOUNT = (first amount + EXTRA +
scale-1)/scale-1; **INT_MASK = last_task->int_mask; INT_CLEAR = first_task->int_mask**; PC_TASK_CONTROL =
((0x6 | task_pp_en) << 16) | task_number; PC_DMA_BASE_ADDR = task_base_addr (0 in the capture); then a single
PC_OP_EN 1→0 pulse. Completion is by **interrupt** (wait_event on job->int_status, only the last task's int_mask
enabled), not our raw-PC_DONE poll.

Three facts fall out:
- **The RK3576 config matches ours exactly** (pc_task_number_bits=16, pc_task_status_offset=0x48,
  pc_data_amount_scale=2, max_submit_number=(1<<16)-1=65535). 65535 ≫ 29 tasks, so the vendor runs the whole
  graph in ONE submit — not small chunks. Config is not the difference.
- **The vendor's per-task regcmd has NO in-stream broadcast OP_EN.** Its targets are only 0x201/0x801/0x1001/
  0x2001 (CNA/CORE/DPU/RDMA) — never the 0x81 broadcast. So Mesa's per-task 0x81 op_en (value 0x1d) is a Mesa
  invention, and stripping it (ROCKET_STRIP_OPEN) is what matches the vendor. The units are meant to engage from
  the per-task S_POINTER arming (0x1004=0xe, which each task's regcmd carries) plus the one PC_OP_EN pulse — no
  per-task op_en at all.
- So with the vendor-matching stream (no in-stream op_en, one pulse, task_number=N), the units DO engage but
  task 0 never completes its DPU write (output distinct=1, PC_TASK_STATUS stuck at 0) — the PC waits for a
  completion that never comes and never advances. **Yet the identical task 0 completes fine as a task_number=1
  kick** (distinct=239). So the crux is exact and small: something about task_number≥2 mode gates task 0's
  compute completion (the DPU write / the done handshake the PC advances on). That is register/microcode-level.

Fork A campaign from here: find why a task completes as task_number=1 but stalls as task 0 of task_number=N —
by capturing the live unit/PC status of task 0 in each mode side by side, and matching the vendor commit_pc bit
for bit (per-task INT_MASK via a new UABI field, interrupt-driven completion, task_pp_en). The vendor driver is
the map; the seam is the multi-task completion handshake. (Kernel diagnostics for it: the arm/exec dumps
already in rocket_job.c; the vendor recipe above.)

## 2026-07-04 — where it stands: the whole chain runs except one piece, the pointwise weight pre-staging. Cheap paths (C: bank capacity, B: on-chip preload) are closed; the continuous PC submit (Fork A) is the next campaign.

A consolidation, because this is a natural stopping point. Over this run the RK3576 NPU went from a month-long dead
wall to a single, precisely-located gap:
- Multi-task ENGAGE: solved. Dispatch the graph as N sequential single-task kicks (task_number=1 each), not one
  task_number=N PC submit. Every unit engages on every kick.
- The chain FEATURE path: solved. Skip the per-kick pp_state_init (POINTER_PP_CLEAR cooled the on-chip buffer);
  the chained layers now DMA their input and run real MACs.
- The chain WEIGHT path: solved for the DEPTHWISE layers (small weights fetch per kick), NOT for the POINTWISE
  layers — their weight DMA never fires (wt_rd=0), so a pointwise layer computes weightless (bias → relu → the
  output zero-point) and the graph's output collapses.

The pointwise weight is the one remaining piece, and it is architectural. The pointwise config is byte-identical
to the vendor's, so it is not the command stream. The two cheap board levers are now clean negatives:
- **C (CBUF weight-bank capacity)**: giving the pointwise a bigger CBUF WEIGHT_BANK count — 1 and 8 both — does
  not move wt_rd off 0. The vendor uses WEIGHT_BANK=0 (default) and it works, so it is not a regcmd capacity knob.
- **B (on-chip weight pre-load)**: concept-tested and CLOSED. Added a `pw_weight_sram` knob that stages each
  pointwise task's weights into the on-chip NBUF (map 0x3fe80000 → IOVA 0xfff00000) and repoints 0x1110 there.
  The board diagnostic showed the staging never fired: `iommu_map(0xfff00000)` fails (`pw_mapped=0`) — not the
  32-bit-aperture overflow (shrinking the map to 256 K didn't help), so it is a conflict: our Mesa BOs occupy
  that range in the whole-graph domain (they run up near 0xffff0000). Worse, the repeated failed map corrupts
  the domain and the chain regresses to all-0x00. And the NBUF is a fixed HW window — a prior test showed an
  arbitrary IOVA for the weight source doesn't move the CMAC (only the exact 0xfff00000 window does), which is
  exactly the range our BOs sit in. So the on-chip preload can't deliver: the one window that works is occupied,
  an arbitrary one doesn't, and forcing the map damages the IOMMU. Combined with the prior audit (weights via
  NBUF don't reach the CBUF), B is closed.

So the mechanism is settled: the vendor runs the graph as one **continuous** PC submit, and while a layer
computes the PC **pre-stages the next layer's weights into the on-chip buffer**. The depthwise's small weights
we can fetch per-kick; the large pointwise weights genuinely need that pipeline pre-staging, which sequential
kicks don't have. Closing the chain therefore needs **Fork A**: make the continuous multi-task PC submit engage
AND iterate all tasks — which is the wall the sequential kicks routed around ("1/29 then stuck": the units
engage but there is no completion handshake to advance the PC to the next task, and a stall cascades into a
dangerous shared-IOMMU reset / -14). That is register/microcode-level, below the online NVDLA docs, so Fork A is
its own campaign: read the NVDLA RTL (github.com/nvdla/hw) for the PC/executer task-iteration completion logic,
or fall back to extract/replay. Everything up to that one seam works. (Kernel: rk3576-warmchain d54b57d94;
mesa ROCKET_WT_BANK / ROCKET_OUT_SHIFT_ABS diagnostics left in tree.)

## 2026-07-03 (latest, corrected) — Fork A first move: the chain is no longer dead. Skip the per-kick pp_state_init and the chained layers finally engage and DMA their input — but the weight path is still stale, so the CMAC accumulator is empty. The wall became a slope; the FEATURE side is fixed, the WEIGHT side is next.

The chain needs the on-chip buffer warm across layers, which the sequential kicks were cooling. The suspect
was pp_state_init: the kernel re-runs it (S_POINTER group reset + POINTER_PP_CLEAR + the degenerate DS1 default
into both groups) at the head of EVERY kick, and the vendor never does this per task. POINTER_PP_CLEAR resets
the ping-pong so a chained task reads a cleared group instead of the buffer the previous task wrote. And each
task's own regcmd already arms its S_POINTER (mesa writes 0x1004 per task), so the first kick's pp_state_init
is all that's needed for the cold-start engage.

So: run pp_state_init only on the FIRST task of a job, skip it on the within-job re-kicks (rocket.wg_warm_chain).
Board result, MobileNet whole-graph:
- Engage is intact (exec_ever=0xf on every kick), conv0 still computes (distinct=239).
- And for the FIRST time the chained layers are NOT flat zero. Where every layer after conv0 used to be
  distinct=1 / all 0x00 (dead, no DMA, no MACs), they now engage and move: task 1 is uniform 0x80 (not 0x00),
  task 3 is distinct=3 with real values (0x0d/0x7f/0x80), task 4 distinct=4; one chained layer shows
  top dt_rd=50176 / wt_rd=72 (it DMA'd its input and weights) and core dt_wr jumped from 25088 to 100464
  (4x the MACs). Data is flowing across layers now.

It is not correct yet, and a follow-up diagnostic corrected my first read of *why*. The chained outputs
saturate to the output zero-point (0x80/0x7f), so the final result is still degenerate (Top-1 index 0). I first
called this "computes, wrong scale" — a requant problem. **That was wrong.** Forcing the chained-layer OUT_CVT
shift down to an absolute 12 (`ROCKET_OUT_SHIFT_ABS=12`, amplifying the requant by ~2^10 vs the computed
shift 17-25) did not move the output off the zero-point at all — task 1 stayed uniform 0x80, tasks 2/4 stayed
distinct=2 at 0x7f/0x80. If there were a real accumulator being crushed, amplifying it 1000x would light it up;
it didn't. So the chained CMAC accumulator is **empty or negative** (relu'd to zero → output = out_zp), not a
non-zero MAC scaled wrong. Same wall MidG971 is on with RK3568 ("the MAC is empty, the zero-rail is upstream of
the SDP").

The clue is in the counters: some chained layers show **wt_rd=0** — they DMA their input but never fetch their
weights (task 2 and task 4 wt_rd=0, while task 1/3/5 read 36/128/72). A conv with no weights accumulates only
the bias, which after the ReLU collapses to the output zero-point. So warm-chain fixed the *feature* path (the
chained layers now read their input) but the *weight* path is still broken — a sibling of the on-chip-buffer
staleness the feature side had. The next lever is exactly that: why the chained layers' weight fetch doesn't
fire (weight-reuse/CBUF vs a fresh DRAM read, weight bank, or the 0x1110 weight address), so the weights reach
the CMAC the way the input now does. (Kernel: branch rk3576-warmchain, commit d54b57d94, off
rk3576-sequential-kick; rocket.wg_warm_chain=1.)

Narrowing the weight-fetch bug (offline vendor-capture diff, 2026-07-04). First guess was `k_word`: the mesa
encoder sets the CNA kernel-extent word to 0 for any k<3 (`k_word = (k>=3) ? ... : 0`), which for a 1x1
pointwise layer emits 0x1024 = 0x0000_003f — I suspected the zero extent stopped the weight DMA. **Refuted by
the vendor's own bytes:** in the captured 24-task chain the vendor's pointwise tasks (0x100c=0) also emit
0x1024 high-half = 0x0000, and their whole weight-config block (0x101c/0x1020/0x1024/0x1030) is byte-identical
to what the mesa encoder produces. So k_word=0 is correct for pointwise and is not the bug. That collapses the
possibilities hard: it is **not the regcmd** (pointwise config == vendor), **not the mapping** (the weight BOs
are mapped — conv0 and the depthwise layers fetch fine), and **not all weights** — the *depthwise* layers, whose
weights are small (k·k·C), do fetch (wt_rd=36/128). It is specifically the **pointwise** layers, whose weights
are large (Cin·Cout), whose weight DMA never fires. That small-fetches / large-doesn't split is the strong clue:
the same "too big for the on-chip buffer in one go, needs an extra mechanism" pattern the feature side hit when
a 112-wide layer wouldn't fit the CBUF and had to be tiled. So the lead is the pointwise large-weight path — a
weight-bank / block-DMA trigger that warm-chain doesn't cover — the execution-state sibling of the feature CBUF
staleness, now pinned to exactly the large-weight case.

Two board levers, both clean negatives, that close the cheap options and sharpen the cause (2026-07-04):
- **cbuf_reset=1 (H/control-only) + warm-chain**: does NOT clear the pointwise weight-valid state (pw wt_rd
  still 0, feature stayed warm). So the weight-valid, like the feature-valid, is coupled to the AXI/MMU reset
  domain (which cbuf_reset=2 touches but breaks translation) — not the H domain.
- **a fresh pointwise WEIGHT_BANK (ROCKET_WT_BANK=1, pw gets a different CBUF weight bank than the depthwise
  before it)**: does NOT force the pw weight DMA either (pw wt_rd still 0). So it isn't a "bank looks valid"
  skip. (Side effect: it did move a *depthwise* layer's output from distinct=3 to distinct=16 — the bank change
  shifts the CBUF layout — but the pointwise weight fetch is untouched.)

That rules out both the reset-invalidate and the bank levers, and points at the real mechanism: the vendor
runs the whole graph as one **continuous** PC submit, so while a layer computes the PC **pre-stages the next
layer's weights into CBUF** (double-buffering). The vendor's pointwise almost certainly shows wt_rd=0 too — it
doesn't DMA at run time, it reads weights that were staged during the previous task. Our sequential kicks have
no such pipeline, so a pointwise layer's weights are never pre-staged and it computes weightless (bias only →
relu → zero-point). warm-chain got the *feature* and the small *depthwise* weights across with per-kick
fetches; the large *pointwise* weights are the one thing that genuinely needs the pipeline. So the pointwise
weight is the last hold-out, and it is architectural: it wants either the continuous PC submit (Fork A's hard
wall, where the pre-staging is free) or an explicit kernel-side weight pre-load before each pointwise kick.
(Mesa: ROCKET_WT_BANK knob added to rkt_regcmd.c for the test; kernel branch rk3576-warmchain unchanged.)

## 2026-07-03 (latest) — forcing a per-job NPU power-cycle to clear CBUF: it fires, but the power domain hangs on the way back up. Fork B (clear the on-chip buffer in software) is now fully exhausted.

The chain needs a cold on-chip buffer per layer. cbuf_reset=1 can't invalidate it and cbuf_reset=2 corrupts
translation, so the remaining idea was the cleanest reset of all: a full NPU power-cycle between layers, which
clears the CBUF SRAM (the next layer starts cold like conv0) AND re-inits the MMU through the resume path's
rk_iommu_enable (force_reset passes on a freshly powered MMU, no -EFAULT). Run each layer as its own job and
force a synchronous runtime-suspend at each completion (added a `force_powercycle` module param, default off).

It took three tries to make the power-cycle actually happen, and the lessons are worth keeping:
- `pm_runtime_put_sync` did nothing: with autosuspend enabled it only runs the idle path and re-arms the 50 ms
  timer, which mark_last_busy keeps pushing out under back-to-back jobs — the NPU powered off once in 185 jobs.
- Even ordering the put before the fence signal and bypassing the suspend's is_idle check wasn't enough — the
  scheduler credits the next job and its pm_runtime_get races the put. The fix is `pm_runtime_put_sync_suspend`
  (bypasses autosuspend), done BEFORE signalling the fence so, with credit_limit=1, no next-job get can race it.
- With that, the power-cycle finally fires: at the first job's completion the log shows put_sync_suspend ->
  "rpm: suspend" -> the genpd printing `npu0 -> OFF`, `npu1 -> OFF`, `npu0 -> ON`.

And then the board hangs, dead, right there. It wedges at `npu0 -> ON` — *before* the device runtime_resume
callback runs (its first dev_info never prints), so the hang is in the genpd power-ON of the NPU domain, below
the rocket driver. The tell is `npu1 -> OFF`: powering down core 0 cascades the *parent* NPU power domain off
(taking core 1 with it), and bringing it back up immediately wedges on the power-ack. The vendor never powers
the NPU down mid-inference — it holds the whole graph on one powered session — so this rapid off/on path is
unexercised silicon, and it doesn't come back. force_powercycle=1 hangs the board every boot; default 0 is
untouched and safe.

So the "cold buffer per layer" hypothesis is still unproven (we hang before the next layer computes), but every
software lever to reach it is now spent: cbuf_reset=1 (no-op), cbuf_reset=2 (breaks translation), power-cycle
(hangs the power domain). Fork B is closed. The way forward is Fork A — one continuous PC submit so the on-chip
buffer stays warm across layers the way the vendor's does — which means cracking the multi-task PC engage the
sequential kicks routed around. (Kernel: branch rk3576-powercycle, commits 22751c4a9 + 5619e39bd + 6aeba36a6,
kept for reference; DANGER: force_powercycle=1 hangs the board.)

## 2026-07-03 (latest) — the chain break is NOT a Mesa bug: our chained-layer regcmd is byte-identical to the vendor's, and the vendor chains layers through DRAM. The wall is CBUF continuity, which the sequential kicks break.

After the sequential-kick engage win (below), the whole graph still breaks conv0->layer1. To settle whether
that is our command stream or the dispatch, I parsed the vendor's own captured 24-task chain (bo00..bo04 +
meta) offline and diffed it against what we emit and against the live CNA registers on the board.

Two things fell out, both decisive:

- The vendor chains layers through **DRAM**, not a magic on-chip path. Every intermediate activation lives in
  one 2 MB buffer (bo2); each layer's CNA input address (reg 0x1088) points at a real offset in bo2, and the
  layer-boundary tasks are *fresh* reads (no CBUF-reuse bit: 0x1038=0x7, 0x103c low half 0), while only the
  within-layer tiles reuse CBUF (0x1038=0x80000007). CBUF is far smaller than 2 MB, so activations genuinely
  round-trip DRAM between layers.
- Our chained-layer regcmd is **byte-identical** to the vendor's. Replaying the vendor's exact task-1 bytes,
  the live CNA registers read back equal to the capture (0x100c=1, 0x103c=0x00380000, 0x1040=0x14000000,
  0x1044=0x00700038, 0x1090=0x1c0, 0x1094=0x3100, 0x1098=0x27d0), with 0x1088 correctly remapped to a
  filled, IOMMU-mapped buffer. And Mesa's whole-graph submit already puts every intermediate tensor in the
  BO set (as an output; the producer's output tensor and the consumer's input tensor are the same aliased
  BO), so the input is mapped and filled. So it is not the command stream, not the addresses, not the mapping.

What's left is the only thing that differs: **execution context.** conv0 is task 0 of the job — a cold start —
and it DMAs its input (`dt_rd=9408`). Every task that is *not* first in the job skips its input DMA
(`dt_rd=0`) and reads an empty on-chip buffer, producing zero. The CNA treats a non-first task's input as
"already staged in CBUF by the previous task." In the vendor's **continuous** single PC submit the CBUF
really is warm from the previous task, so skipping the DMA and reading CBUF is correct; the 2 MB DRAM buffer
is the spill for what CBUF can't hold. Our **sequential kicks** put a full teardown between tasks
(pp_state_init's POINTER_PP_CLEAR, the OP_EN 1->0 cycle, ~30 µs of gap), so the CBUF is "warm-looking but
empty" and the skipped DMA reads nothing.

So the chain needs CBUF continuity, and sequential kicks (which we needed for *engage*) are in tension with
it. Confirming the tension from the other side: forcing the re-DMA with a per-job on-chip-buffer reset does
work but is coupled to address translation — cbuf_reset=1 (control/H only, IOMMU-safe) is harmless but does
NOT invalidate the "staged" state (chained layers still `dt_rd=0`, conv0 still computes, no saturation);
cbuf_reset=2 (touches the CBUF AXI/MMU bank) does force the re-DMA but corrupts translation and saturates.
The CBUF-valid invalidate and the MMU bank are the same reset domain.

Net: the way forward is the vendor's — one continuous PC submit so the CBUF stays warm across layers — which
means cracking the multi-task PC engage (the wall the sequential kicks routed *around*), now knowing that
single-task arming engages and that continuity is what the chain actually needs. Forcing per-task DRAM reads
in the kicked regime is the other fork, but every software CBUF-invalidate lever there is exhausted or breaks
translation.

## 2026-07-03 (later) — the multi-task ENGAGE wall is DOWN: dispatch a job as N sequential single-task kicks, not one task_number=N PC submit

This supersedes the addendum below that concluded "both remaining walls sit below the register surface;
the next real step is the NVDLA RTL." The engage wall did **not** need the RTL. It needed to stop asking
the RK3576 PC to iterate the tasks itself.

The RK3576 PC never engages the compute units for `task_number ≥ 2` (one OP_EN, PC walks the task array).
A single task engages reliably (proven in replay: an isolated conv and an isolated depthwise both compute).
So dispatch a multi-task job as **N sequential single-task kicks**: each kick `task_number = 1`, one OP_EN,
advancing one task per DPU-done interrupt, all inside **one job** with no soft/CBUF reset and no iommu detach
between kicks. Two lines in `rocket_job.c`: `next_task_idx++` (which re-arms the re-kick branch that was
already in the DPU-done handler) and `PC_TASK_CON` task_number = 1. This is the mainline RK3588 model.

Board result, MobileNet whole-graph submitted as one 29-task job:
- Every kick engages — `exec_ever=0xf` (CNA+CORE+DPU+RDMA all set S_POINTER bit16), `rawor` error bits all 0,
  `TASK_CON=0x00010001` (task_number=1), `DATA_ADDR` advancing through all 29 tasks. The re-kick fires.
- conv0 (task 0) reads its external input (`top dt_rd=9408`, `wt_rd=96`), computes (`core dt_wr=25088`), and
  writes a **real** output to DRAM: `buf[1] out task=0 iova=0xfeb2d000 distinct=235 nz=4092/4096`.

The engage wall we had concluded was below the register surface is crossed in the kernel by reframing dispatch.

What remains, now cleanly isolated and standing ALONE: the **conv0→layer1 data handoff**. task1 onward read
nothing from DRAM (`top dt_rd=0`) and output all-zero (`distinct=1`), cascading to an empty final result
(NPU Top-1 index 0 / conf 0 vs CPU 412). This is the same on-chip-buffer-persistence wall from the entry
below — the chained layer's input never reaches it — but it is no longer entangled with engage, and it is
**above** observability: conv0's output is already sitting in DRAM (`0xfeb2d000`, real), and mesa has already
linked the chain (task N out iova == task N+1 in iova). The next lever is to make each intermediate task read
its input from the previous task's DRAM output BO — the SPREAD-per-op path that already computes single layers
correctly (dw112 `distinct=213`), now inside one engaging job. That is a mesa WG-packer / per-task input-address
fix, not a register mystery. (Kernel: branch `rk3576-sequential-kick`, commits 86457835b + 718707939.)

## 2026-07-03 — the depthwise is not a silicon wall: the "computes nothing" was a stale on-chip-buffer reuse, and it reproduces with the vendor's own bytes

This overturns the two 2026-07-02 entries below ("the depthwise is a wall of its own"). The way to
settle "is this our software or the silicon" was to stop generating command streams and instead replay
the *exact bytes the vendor's stack submits*: capture one operation's payload at runtime (the command
stream + input/weights/bias, byte-for-byte) and feed those same bytes through the mainline rocket driver.

- A standalone depthwise (the vendor's captured dw112, tiled into 6 pieces), replayed as 6 single-task
  jobs, **computes** — it engages, reads its input from DRAM (`dt_rd=20384`), and writes a rich output.
  So the depthwise is **not** a silicon wall; "a single-task depthwise does no MACs" was wrong.
- The multi-task version of the *same* bytes (one job, task_number≥2) still walls (never engages). So the
  multi-task engage wall is real and lives in the kernel's PC drive — same bytes, only the submit grouping
  differs.

Then the real puzzle. In Mesa's Path B (each row-tile its own single-task job) conv0 computes but the
depthwise after it reads nothing (`dt_rd=0`) and outputs zero. To isolate it cleanly I captured the
vendor's 4-layer chain (conv0→dw1→pw1→dw2) and replayed the whole thing spread. The result is decisive:

- conv0, which reads the **external input**, DMAs it (`dt_rd=9408`) and computes.
- every **chained** layer, which reads a previous layer's **intermediate** output, reads nothing
  (`dt_rd=0`) and produces nothing — the on-chip buffer ends up holding only conv0's output.

This reproduces with the vendor's own bytes, so it is not a Mesa bug. And the chained depthwise's command
stream is byte-identical to the standalone depthwise's (same buffer-reuse bit, off) yet one DMAs and the
other doesn't. So whether a layer fetches from DRAM or reuses the on-chip buffer is **not in the command
stream** — it's the on-chip buffer's entry-valid state. The vendor runs the whole graph as one submit, so
each layer's input genuinely still *is* in the on-chip buffer from the previous layer, and reading it there
(no DMA) is correct. Path B ends each layer as its own job, the buffer isn't persisted, the next layer
reuses a stale/empty buffer and gets zero. **That is the whole conv0→depthwise wall.**

Confirming it: a per-job on-chip-buffer reset (`rocket.cbuf_reset=2`) forces the chained layers to re-DMA
— they go from `dt_rd=0` to `dt_rd=20384` and start writing. But that reset also disturbs the buffer's
address-translation bank and the driver doesn't re-establish it per job, so every layer's output saturates
(all `0x7f`/`0x80`); a stronger reset kills everything. Mechanism confirmed, blunt hardware reset can't fix
it cleanly.

The takeaway is architectural: this NPU is built for whole-graph execution, layers chained through the
on-chip buffer. Path B (independent jobs, DRAM round-trips) fights that design — the chained-layer command
streams want to read the on-chip buffer, and forcing a re-fetch needs a buffer invalidate the hardware only
exposes via a reset that breaks address translation. So the way forward is the vendor's own: run the whole
graph as one submit and crack the multi-task engage wall — now with the byte-exact replay as a tool to see
exactly where the engage breaks.

Two direct fixes tried and ruled out. Forcing the chained layer to re-fetch with a per-job on-chip-buffer
reset corrupts *any* compute, not just the chain — a lone conv goes from byte-exact to maxdiff 255 —
because the reset disturbs the buffer's address translation and re-establishing it dies (`-14`). And
writing the vendor's ENABLE_MASK from the CPU to force the multi-task engage just hangs the board (that
register is already written by the command stream, so a raw CPU write to it is redundant and wedges the
bus). So neither the reset nor the enable-mask is the lever. Nor is the on-chip-buffer bank: giving the
chained layer a different data-bank offset (CBUF_CON0 FC_DATA_BANK) leaves it at `dt_rd=0` — the reuse
isn't a command-stream field at all (DATA_REUSE is already 0). So the trigger for "reuse vs re-fetch" is
the on-chip buffer's entry-occupancy *state*, left by the previous layer, with no clean register lever.
That is where this stops being crackable by knob-sweeping: the fix needs the CBUF entry-management
semantics (the NVDLA CDMA/CBUF spec this NPU derives from), not another guess.

The other wall — whole-graph, where the layers *do* chain through the on-chip buffer — has its own
below-observability stop: the multi-task program counter iterates the tasks but the compute executers
never start (the engage bit never sets). The NVDLA programming guide gives one concrete rule — op_enable
must be issued in reverse (downstream-first) order — but reversing it changed nothing; and once the
per-job pointer init is on, the geometry *does* latch into the executer's group and the pointer *is*
armed, yet the executer still won't start. So both remaining walls (the buffer-reuse trigger, and the
executer start) sit below the register surface the online NVDLA docs describe; the next real step is the
NVDLA RTL, not another register guess. Everything up to here — the depthwise being real, the stale-buffer
mechanism, the exact walls — is characterised and reproducible.

## 2026-07-02 (live config) — the depthwise is fully, correctly configured and engaged, and still computes nothing. Not a config bug.

Chasing the intuition that this is software, not silicon, I dumped the depthwise tile's *live* registers
(what the hardware actually holds mid-run, not the command stream I send) and lined them up against a
convolution that does compute. Everything is right:

- **Output writer (DPU): configured** — real destination address, correct output geometry for the tile
  (`0x4018=0xfea69000`, `0x4024=0x59`=89 rows). It is set up to write.
- **Input engine (CNA): configured for depthwise** — the depthwise-mode bit is on (`0x100c=1`), the
  convolution control and the weight byte count (`0x101c=0x240`=576, correct for this depthwise) are right.
- **MAC array (CORE): configured** — output-channel count and the rest match.
- Weights were DMA'd in, the units are engaged (the executer bit is set), and the input is being read.

And the depthwise still writes nothing — an *exact* zero, not a wrong non-zero. A wrong non-zero would mean
the MAC ran with the wrong setup; an exact zero means the MAC array did no work at all. So there is no
visible configuration bug: every register the driver can read is correct and live. Two things this rules
out for good: it isn't a config mistake, and it isn't the engage wall either — the depthwise tile *does*
engage; engaging and computing are separate, and for the depthwise the second doesn't follow the first. The
op is set up perfectly, wakes up, reads its input, and produces nothing. The vendor's depthwise computes
only as a multi-task job; a single-task depthwise, however perfectly configured, does no MACs. That
single-task-vs-multi-task line is the whole remaining mystery.

## 2026-07-02 (Path B) — routed around the multi-task wall, fixed two real bugs, and the depthwise turned out to be a wall of its own after all

The plan was to never hand the hardware a multi-task job: the wide layers only tile because the on-chip
buffer holds one row-window at a time, so emit **each row-tile as its own single-task job** (Mesa,
`ROCKET_TILE_JOBS`) and let the kernel chain them. Single-task jobs engage reliably, so this should sidestep
the multi-task engage wall. Chasing it down found two real bugs and then the truth about the depthwise.

**Bug 1 — a double-free (heap corruption).** With every tile a separate job, the per-op input/output BO-handle
arrays got freed once per tile-job in cleanup — an N-free for an N-tile layer. That corrupted the heap and
hung the run (a userspace timeout, no output). It was a latent bug in the existing "spread" path, only ever
triggered once tiled layers started using it. Fixed (each job owns its handle copies). After the fix, **conv0
computes under Path B** (a real feature map, `core dt_wr=25088`) — so a submit of ~30 single-task jobs is
fine; the hang was purely the double-free.

**Bug 2 — a ping-pong split.** The single-task depthwise tile came up with its producer on buffer group 0 and
its consumers on group 1, so the consumers read the empty half and wrote zero. The cause is a pointer-ping-pong
enable bit that auto-advances the consumer pointer; arming the tile with that bit off (`S_POINTER=0x04`,
executer-enable only) lined all four units up on group 0 — confirmed in the registers: `cna/core/dpu/rdma
sp = 0x00010004`, all engaged, all aligned.

**And the depthwise still drew zero.** Fully aligned, all four units engaged, reading its input — and the DPU
wrote nothing (`dt_wr` never moved past conv0's 25088; the tile output stayed `0x00`). So the ping-pong split
was a red herring: fixing it changed nothing. With both confounds removed — the multi-task engage *and* the
ping-pong — what's left is exactly the wall from before: **the depthwise-mode op does not fire its output
write as a single task, regardless of alignment, engagement, or operands.** The vendor's depthwise computes
*only* as a multi-task job (per-task re-arm); ours won't engage multi-task. So the depthwise is blocked both
ways — single-task, the DPU write never fires; multi-task, the units never engage — and both live below the
registers. Path B routes around the engage wall for ordinary convolutions and fixed two genuine bugs, but it
does not carry the depthwise. The one lever left is a hardware trace of what the vendor's DPU does per task in
the multi-task path that a single task doesn't.

## 2026-07-02 — the two walls collapse to one: multi-task engage. The depthwise is not a separate wall; the gap is below observability, and the only untested difference left is firmware

Added a per-unit engage-state dump to the kernel (each unit's `S_POINTER` [bit16 = executer engaged, low
nibble = ping-pong group] and `S_STATUS`, at rest and right after the go-pulse) and compared a working run
to a failing one, both as the first inference after a clean boot so nothing is confounded by the
second-inference degradation.

**The multi-task wall is an engage failure.** A byte-exact conv forced to `task_number=2` (only that field
changed):

```
working (task_number=1): all 4 units sp=0x0001000f  (bit16 SET = engaged),  STAT=0x0c, core dt_wr=12800
failing (task_number=2): all 4 units sp=0x0000000f  (bit16 CLEAR = not engaged), STAT=0x05, dt_wr=0
```

So `task_number>=2` makes the sequencer advance its task counter and report "done" while the compute units
never engage — not one of them sets bit16, the output writer never writes a byte.

**The depthwise looked like a second wall, then wasn't.** As a (vendor-never) single full-height task the
depthwise *does* engage (bit16 set on all four) but splits the ping-pong: the CNA producer advances to
group 1 (`0x0f`) while the consumers stay group 0 (`0x0e`), so the consumers read the empty group and the
output is zero, while a standard conv keeps all four aligned and computes. That's a concrete, register-level
cause — but it was only ever seen under `NO_DW_TILE`, a shape the vendor never emits (it always row-tiles a
112-wide depthwise). So I checked how the vendor's *tiled* depthwise handles the parity, two ways: its
command stream arms every unit to group 0 (`0x0e`) on **every** task (no alternation), and — instrumenting
the vendor's own driver and running it on the board — its multi-task depthwise settles with all four units
aligned at group 0 and computes (`core dt_wr=25088`). It never uses the producer-ahead pattern. So the
split is a `NO_DW_TILE` artifact: the vendor avoids it by tiling into small tasks and re-arming group 0 each
task. **The depthwise is not a separate silicon wall — it's just the first layer forced to be multi-task.**

**Where it ends, honestly.** Everything now reduces to one thing: the units engage per iterated task on the
vendor and don't on the open driver — with a per-job setup I've matched to the vendor byte-for-byte (the CPU
arming, the command-stream `S_POINTER` writes, the init sequence, the go-pulse), and single convolutions
prove the datapath is addressed correctly. The vendor engages its units from the `S_POINTER` arming plus one
pulse with no in-stream enable; the open driver's units only wake from an in-stream enable that restarts the
sequencer, so it can't iterate. Trying to catch *how* the vendor re-engages between tasks, on the board, the
vendor finishes a two-task depthwise in microseconds — faster than a CPU register poll can sample — so the
per-task re-engage is below what software can observe on either side. Software knobs, static command-stream
comparison, and a live vendor capture are all exhausted. The one structural difference left untested is
**firmware**: the vendor stack boots Rockchip TF-A + OP-TEE (NPU clock/power via secure SMC calls), mainline
boots neither, and a secure-world NPU init is exactly the layer a vendor capture can't isolate. That's the
next dig, and it's a big one.

**Update — firmware ruled out, and the real way forward.** I did the dig: built an image with a mainline
RK3576 OP-TEE port (BL31 + BL32, TZDRAM reserved in the DTB) and booted the same rocket kernel on top of it.
OP-TEE really ran — its own secure-world banner prints on the console, the DDR firewall is live — and the
multi-task job failed *byte-for-byte identically*: not one unit engaged, nothing written. So it isn't the
presence of the secure firmware either. The multi-task engage difference is below what software can observe
on either side; without a hardware trace it isn't reachable, and it's the one thing between here and a
running MobileNet.

But "can't crack the multi-task engage" is not "can't run MobileNet." The wall only bites *multi-task* jobs
— a job carrying more than one task. Single-task convolutions engage and compute reliably; that's proven.
The wide layers only need multiple tasks because one row-tile at a time is all the on-chip buffer holds — so
the fix is to stop packing the tiles into one multi-task job and instead emit **each row-tile as its own
single-task job**: its own input rows staged from DRAM, its own weights, its own slice of the output,
chained by the kernel like the per-op path already chains layers. It costs re-staging weights per tile (no
reuse) but every job is then a task-count of one, which the hardware runs. That's the concrete next build —
in Mesa, not the kernel — and it routes around the one wall left standing instead of trying to break it.

## 2026-06-30 (later) — on-chip weight SRAM ruled out; full register diff = vendor superset; multi-task wall confirmed by controlling inference order

Continued from the two-walls result below. Three things settled by board tests, judged by the output buffer
and the DMA byte counters (`core dt_wr`).

**1. On-chip weight SRAM (the vendor's "nbuf") is NOT the depthwise lever.** Made the kernel stage each
depthwise layer's weights into the 1 MB on-chip NPU SRAM (the exact region the vendor uses) and repoint the
CNA weight-source register at it. This needed reserving the on-chip IOVA window from the BO allocator first
(the high-IOVA BOs collided with it: `iommu_map ... ret=-98`). After the reserve it works — the log shows all
13 depthwise layers staged (`staged weights 0x...->SRAM`), `conv0` still computes — yet the depthwise output
stays exact `0x00`, the weight staged 10 ms before the op ran. So the weight *source location* (DRAM vs
on-chip) changes nothing.

**2. The full register diff is a vendor superset — no missing register.** Compared every register the open
driver writes for the depthwise (CNA + CORE + **DPU + DPU_RDMA**, not just the conv-engine block) against the
vendor's. The open driver writes a strict **superset** (138 vendor entries, 142 ours; the 4 extra are the
per-unit enable writes). Every value difference is explained by tiling geometry, the sample model's different
quantiser, or those enables. The one unexplained config word (`CNA 0x1080`) was forced to the vendor's value
— the depthwise still output zero. The depthwise command stream is exhausted.

**3. The multi-task wall is real — confirmed by controlling for inference order.** A long-standing confound:
a *second* inference after boot degrades to zero on its own (inherited dirty state), so any A/B where the
"broken" case ran second is suspect. Reversed it — ran `conv2d-cal` with the PC task-number forced to 2 as
the **first** inference after boot, valid submit:

```
wgsubmit: TASK_CON=0x00010002 DATA_ADDR=0xffef6000 DATA_AMOUNT=0x49   (task_number=2, valid)
cnalive:  exec_ever=0x0   (not one unit engaged; a working single task = 0xf)
perf:     core dt_wr=0    (the DPU never wrote; force=0 single task = dt_wr=12800, byte-exact)
buf out:  distinct=1      (zero)
```

Only the `TASK_CON` task_number differs from the byte-exact single-task run, and `task_number>=2` takes the
output to zero with the units never engaging — even on a clean first inference. So the multi-task wall is not
the second-inference confound; it is real. (`dt_wr` also separates the two: the multi-task wall is `dt_wr=0`,
the units never fire; the second-inference degradation is `dt_wr>0` but the output is wrong.)

**Mechanism (from the vendor's own driver source).** The vendor engages the units with no enable-mask
register write at all (that register is out-of-map on the vendor — reading it oopses) and **no in-stream
enable in the command stream**: just one `PC_OP_EN=0x1` pulse plus each task's in-stream `S_POINTER` writes,
which the PC applies per task. The init sequence matches ours byte-for-byte. The open driver's units, by
contrast, only engage from an **in-stream broadcast enable** (a write to `PC_OPERATION_ENABLE` inside the
command stream) — and that write *restarts* the PC, so with `task_number>=2` the units never latch. Drop the
in-stream enable to match the vendor and the units don't engage at all. So the gap is not the enable-mask
register, not the init, not the submit sequence (all identical) — it is the silicon-level question of why our
units need an in-stream `PC_OP_EN` to engage while the vendor's engage from the `S_POINTER` arming + the
pulse. Software knobs are exhausted; the next data needed is a vendor capture of the per-task engage during a
real multi-task run.

## 2026-06-30 — two separate below-the-register walls: the depthwise op, and multi-task dispatch

Chased whether the depthwise zero is actually the multi-task dispatch wall — the depthwise is row-tiled
into a `task_count=2` job (standard convs are `task_count=1` and compute). Two clean board tests, judged
by the output buffer:

- **Multi-task PC probe** (conv2d-cal duplicated into 2 *real* identical tasks): a single task is
  byte-exact; 2 real tasks are degenerate for **every** OP_EN variant (per-unit `0x1d` / `0x1`, fully
  stripped). The clean run: the units engage (all four `bit16` set), the geometry latches (real `DS1`,
  not the ping-pong default), the PC completes task 0 — then raises `PC_DONE`, never advances to task 1,
  output zero. Every observable signal equals the working single-task run **except `TASK_CON`
  task_number (1 vs 2)**. So `task_number>1` breaks the compute through something no register exposes.

- **`ROCKET_NO_DW_TILE`** (emit the 112-wide layer as one full-height task instead of row-window tiles →
  `task_count=1`): the depthwise is now a single task and **still** outputs exact `0x00` — not garbage,
  so not a CBUF overflow — while the standard convs on the same run compute. So the depthwise zero is
  **NOT** the multi-task wall; it fails as a single task too. It is depthwise-*mode* specific.

- **Clean single-task depthwise** (`NO_DW_TILE`): inert to all three operands — weights (filled with a
  constant), input (a real feature map from conv0), and a forced bias-add jammed straight into the
  requant output stage. None move the output off zero. The op writes nothing.

So there are **two separate walls below the registers**: the depthwise-mode op (writes nothing, the
depthwise layers) and the multi-task PC (`task_number>1` breaks the compute, the whole-graph + tiled
layers). Both have command streams byte-identical to the vendor's; software probing is exhausted on the
depthwise. The one structural thing the vendor does that the open driver doesn't is **park the weights
in the 1 MB on-chip NPU SRAM** — RK3576 is the only chip in the family wired for it. That's the next dig,
and it's in the kernel.

## 2026-06-29 — per-op path: standard convs byte-exact, but the DEPTHWISE op writes no output (below register observability)

Whole-graph (WG) single-job dispatch is an open problem (the unit engage/complete handshake — units
either compute but the in-stream OP_EN restarts the PC, or the PC iterates but the units don't engage;
exhausted the knobs). So pivoted to **per-op** (one DRM job per layer) to reach a *correct* end-to-end
first. All results below are from board tests judged by the output buffer (the only reliable oracle).

**per-op chaining is sound.** mesa shares each intermediate tensor's BO by index; the kernel serialises
the N per-op jobs via dma_resv implicit fences (job N+1 waits for job N). On a clean board conv0
(standard firstconv) computes — `out distinct=242`, a real feature map — and conv2d-cal is byte-exact.
(The old "conv0 ~10% race" was a confound: a boot script auto-ran a WG MobileNet that wedged the engine
before every test; disabling it made conv0 reliable.)

**MobileNet dies at the first depthwise (layer 1).** Per-layer dump: `conv0 out distinct=242` (real) →
`dw1 in distinct=238` (= conv0's real output, so the chain propagates) → `dw1 out distinct=1, all 0x00`.

**The depthwise op produces no output — and it is not mesa's doing.** Three board tests:
1. *command stream*: mesa's depthwise CNA+CORE config is **byte-identical to the vendor's** for the same
   conv (49 registers: `100c=1` dw-mode, `1018` CONV_CON, `101c=0x240` weight bytes, `3018` CORE, …).
2. *weights* (`ROCKET_DW_WTEST`): fill the whole depthwise weight buffer with `0x7f` → `dw1 out` still
   `0x00`.
3. *bias-add* (`ROCKET_DW_ATEST`): force the requant add operand `A=0x2000` (output = `requant(MAC+A)`,
   so A reaches the output regardless of the MAC) → `dw1 out` **still** `0x00`.

Input, weights, AND a forced bias-add all change nothing → the depthwise op never executes its
compute+write; the output stays `0x00`. Standard convs write correctly on the same DPU/kernel, with all
operands staged identically. So it is **depthwise-mode-specific, below register-probe observability, and
not the command stream / weights / layout / requant.**

**Net.** Byte-correct end-to-end MobileNet on RK3576 rocket is blocked by a depthwise-mode execution
wall (same class as the WG engage wall) — not reachable from mesa, whose every input is verified
identical to the vendor. Remaining paths: a hardware execution trace, or the on-chip weight residency
the vendor uses (the 1 MB NPU SRAM + `cache_sgt`, which RK3576 is the only config to wire up and rocket
lacks). Tools added: `ROCKET_DW_WTEST` / `ROCKET_DW_ATEST` / `ROCKET_DUP_TASK` (mesa),
`rocket.wg_force_tasknum` (kernel), `S98mndump` (auto per-layer buffer dump at boot).

## 2026-06-27 (SOLVED) — conv2d is byte-correct; the dominant bug was the C scale fixed-point, not the float surface

`conv2d-cal` (per-tensor, `in_zp=128` — the model called "welded-shut / blob-only" below) now matches the tflite CPU
reference: **100% byte-exact vs the relu reference over the whole output** (constant input maxdiff=0, ramp maxdiff=1 =
int8 rounding). The "float surface is the dominant, non-derivable error" conclusion below was wrong — the float surface
was never the problem. Three derivable fixes, all found by trial-and-error env-knob sweeps judged by the maxdiff oracle:

1. **ABC-buffer C scale fixed-point.** Emit `C = round(16*rel)` (Q4), not `round(16384*rel)` (Q14). The BS stage applies
   C as a raw multiplier then shifts right by 4, so 1.0 = 16; the `0x4000` over-scaled by 2^10 and railed every output
   to 0/255 — the long-standing "all grey / saturated" wall. C sweep: C=16384 → 50% saturated, C=1 → 0%, C=16 sharply
   optimal (exact jumps to 94%).
2. **CNA pad value (`0x1084`) = `input_zero_point - 0x80`,** not the hardcoded `0xffffff80`. `0xffffff80` (pad with 0)
   is correct only for `in_zp=0` (image input). For `in_zp=128` the padded taps added a wrong term → the whole output
   **border ring** was wrong (the last ~6%; the interior was already 100% exact). A control run with the old value
   reproduced the broken border.
3. **Bias operand `A = bias_in`** for `in_zp=0x80` (drop the `0x80` a_scale and the `sw` term).

`wt_zp` is corrected by the `B` term already in the ABC buffer (the HW multiplies it by the per-output input-sum) — not
by packing it into the weights. The HW also applies a **RELU on the accumulator** (negative → out_zp): correct for
MobileNet's ReLU6, only visible here because `conv2d` has no activation. Patch:
`mesa-patches/rk3576-conv2d-int8-WORKING-2026-06-27.patch`. Next: MobileNet (per-tensor, every layer ReLU6).

## 2026-06-27 (next wall) — MobileNet runs all 28 layers on the NPU for real, but the dispatch ping-pong zeros it

With conv2d byte-correct, ran the full MobileNet: NPU output all-zero (0/1001 nonzero). First verified it's
**REAL NPU, not a CPU fallback**: 28 hardware jobs (regcmd[1..28], ~30ms each, ~0.84s total, all four units
engaged), NPU invoke 830ms vs CPU 70ms. So the conv stack genuinely runs the whole network and returns zero.
Cause = the **S_POINTER ping-pong producer/consumer parity**: each unit reads geometry (h,w) from one of two
banks and a state machine flips the bank per task; the producer writes the dimensions into one bank, the
executer reads the other (empty), so every layer runs on h=0 → zero. The **mesa-side S_POINTER value is
irrelevant** (ROCKET_SPTR=0x00/0x30/0x0e all identical all-zero) because the KERNEL re-arms S_POINTER in
pp_state_init/hw_submit, overriding the regcmd → the fix is KERNEL-side, needs a kernel rebuild. Progress vs
months ago: the PC now iterates all 28 tasks (was ~1, stalled). Red herrings ruled out: cnalive `ds0 w=0` and
`cube=` are bogus parses (conv2d-cal works with them too); the DPU output geometry (DST) is correct. Next:
kernel PP-parity (rocket_core.c pp_state_init / rocket_job.c hw_submit). add.tflite (has an ADD op) crashes the
board, so it is not a usable minimal multi-task test — need a pure 2-conv model.

**Status:** **the wall is broken.** The bug was the SDP coefficient (bias/requant) buffer in
`rkt_coefs.c`. With it fixed, the live mainline rocket + Teflon path computes a **rich conv
output** (distinct 236–256, full range) instead of the grey zero-point rail — both with the
vendor's exact bytes and with the driver's own regenerated buffer. Remaining: byte-exact.
The dominant error is the **float surface**, and for this **per-tensor** `conv2d` it needs the toolkit's exact
per-channel re-quantised values (proven: shuffling them keeps the sparse structure but still gives maxdiff=255) — a
sparse, compiler-chosen table that is **not derivable from the tflite** (blob-only). But `conv2d` is a synthetic
per-tensor test; the actual target, **MobileNet, is per-axis**, and the per-channel float surface decodes cleanly to the
dequantised weights (the `idg` captures, months ago). **Next direction: move the encoder + the measured maxdiff loop onto
a per-channel conv, where the float surface is the weights — not the welded-shut per-tensor `conv2d`.**

- HW: Radxa ROCK 4D (RK3576). Stack: mainline **rocket** accel driver + **Mesa Teflon**.
- Reference: vendor `rknpu` + RKNN runtime runs the same MobileNetV1 correctly on the same board.
- CPU ref: Top-1 653 / conf 0.887. NPU: Top-1 0, output all zero-point.

## 2026-06-24 (measurement unblocked + bisect) — the float surface is the dominant error, not A/B/C

Unblocked the byte-for-byte `maxdiff` (the board wedged before the userspace line — the post-job pm_runtime autosuspend
powers the NPU off, `nputop` fails to idle, a cpu rail times out `-110`, console dies). Fix is **sysfs, no kernel
rebuild**: force runtime PM off so the NPU stays powered through the test (`/sys/devices/**/npu*/power/control = on`).
Both segments + the END marker now print.

The number is sobering: the driver's own contiguous-A + dense-float reconstruction is `distinct=256` but **maxdiff=255,
mean|diff|=78, exact=0.7%** — it computes and is almost entirely wrong (datapath tolerance flatters "lights up" into
looking like "correct"). Bisected with two hybrid buffers (loaded via `ROCKET_BIAS_FILE`): **vendor A/B/C + my dense
float → maxdiff=255, distinct=12** (near-degenerate). So even with the *exact* per-channel terms, my float surface is
wrong → **the float surface tiling is the dominant error.** (My A/B/C is also wrong — only 14.9% byte-identical to the
vendor's, `0x80*(sw+bias)` is far off — but secondary.) The vendor float region is **sparse**: 626 nonzero of 4944
slots, and the values don't match any weight order I can read — so the per-tensor `conv2d` float surface likely isn't the
dense dequant-weight array the per-channel `idg` captures decoded months ago. Cracking that sparse scatter is the
remaining hard piece — but it's now **measurable** (drive the hybrid's maxdiff down). Harness: `S97` power-keepon +
`test_conv.py` os._exit; hybrids in `dirty/npu-test/H-myfloat.bin`, `H-myABC.bin`.

## 2026-06-24 (BREAKTHROUGH) — the grey broke: the live driver computes a rich conv from a fixed bias buffer

After confirming the bias buffer is the bug, fixed it in `rkt_coefs.c` and ran the **live** Teflon path (not replay) on
`conv2d-cal`, reading the kernel output readback:

- **Milestone (load the known-good bytes):** `rkt_coefs.c` loads `vendor-bias.bin` verbatim → `buf out distinct=256
  nz=4091/4096 min=00 max=ff` — a real feature map on the live mainline rocket + Teflon driver. Proves the road is
  paved: regcmd, weights, datapath, submit, op_en (broadcast, writes ENABLE_MASK 0xf008 → `exec_ever=0xf`) are all fine;
  the only gap was generating this buffer.
- **The rewrite (the driver's own buffer):** removed the wrong interleaved `[8×i32 A|8×i16 B|8×i16 C]` layout; the new
  default writes **contiguous `A[128]`@0 + `D[128]`@512 (≈A) + a dequant-weight float surface** (`wt_sc*(q-wt_zp)`)
  @`groups*64`. With no file, mesa's own buffer (`bia` A[0]=0x5100=`0x80*(sw+bias)`) → `buf out distinct=236
  nz=3231/4096` — a rich map. **The open driver now generates a working coefficient buffer; the chip computes from it.**

Real upstreamable fixes landed: the interleaved→contiguous BS layout, the non-zero dequant float surface (was always
zero), and the bias-BO size (the old 1280B caused an OOB RDMA read). **NOT yet byte-exact:** rewrite distinct=236 / head
`df00ba00` vs vendor distinct=256 / head `80808080` — `A` is a best-effort `0x80*(sw+bias)` (≠ the vendor operand) and
the float fill is dense vs the vendor's sparse tiling. The surface is tolerant (x0.5/shuffle still compute), which is why
the approximation already runs. Correctness (maxdiff) is unmeasured — the board wedges in BO cleanup before the userspace
line. Next: flush the maxdiff past the wedge (`os._exit` in test_conv.py), then refine the `A` operand encoding + float
tiling toward byte-exact.

## 2026-06-24 (later) — `core wt_rd=0` was a RED HERRING; the bias buffer is the bug; the SDP spec is in the TRM

Re-grounded by replaying the vendor's exact bytes through the kernel and reading the **output**, not the counter:

- **`core wt_rd=0` is a red herring.** The run that COMPUTED a real feature map (`OUT: distinct=98`, 99% nonzero, head
  `0a0b0b05`) shows `core wt_rd=0` too. So that perf counter does not measure CMAC weight reads; `wt_rd=0` is normal.
  Runs #4–#7 (per-unit op_en, enable_mask, BO size, float-const fill) all chased this — wasted. The valid oracle is the
  OUTPUT (distinct under the non-saturating shift, or maxdiff vs CPU), never a perf counter. (The BO-size enlargement is
  still a real fix — the OOB read was real — keep it.)
- **The bias buffer is the bug (clean A/B).** Same vendor weights, same regcmd, swap ONLY the bias: vendor bias →
  `distinct=98 COMPUTED`; mesa bias → `distinct=2 DEGENERATE`. Nothing else differs. After weeks of the bug sliding
  across the weights / dispatch / geometry / a lying counter, it is definitively the SDP coefficient buffer (`rkt_coefs.c`).
  (Earlier I "exonerated requant" — that was the OUT_CVT 0x40ac/b0/b4, which *is* correct; I wrongly conflated it with
  the 0x5020/0x5024 BS buffer, which is the bug.)
- **The missing SDP spec is in the allbilly RK TRM.** `A` doesn't fit `sw`/`bias` (R²=0.002) because it isn't a bias
  formula — it's a **BS-datapath operand**. The TRM: `brdma_data_use` (0x501c) selects which per-channel operands the
  DPU_RDMA reads (bit0 ALU, bit1 CPEND, bit2 MUL, bit3 TRT); `bs_alu_src`/`bs_mul_src`=1 fetch the ALU/MUL operands
  **per-channel from the 0x5020 BS surface**; `out = ((in ALU_op alu_operand) * mul_operand) >> shift`; `erdma_data_mode`
  = per-channel vs **per-channel-by-pixel**. So vendor-bias.bin = `A[128]`+`D[128]` (two per-channel scalar operands) +
  the float surface (the MUL operand in per-channel-**by-pixel** mode = the dequantised weights, one per (ch,tap) — which
  is why there are 4944 floats, not 128). The format is now theory-grounded; the remaining work is mapping each operand
  to its slot and writing the encoder in `rkt_coefs.c`, tested against the OUTPUT.

## 2026-06-24 (cont.) — runs #2–#5: the wall is `core wt_rd=0` (CBUF→CMAC), and an evidence-based way out  *(superseded by the section above — `core wt_rd` is a red herring)*

Built `conv2d-cal` (non-saturating) and ran a sequence, reading the kernel perf counters / `cnalive` as the oracle
(never `distinct`). Each run corrected the previous hypothesis:

- **4-register geometry fix** (generic path `0x1018/0x1024/0x1040/0x1080` → vendor) took effect but did **not** turn
  the MAC on — still `core wt_rd=0`. So the geometry *values* were never the wall.
- **op_en, three ways:** broadcast (units engage, `wt_rd=0`); full strip (geometry sits, `exec_ever=0`, units never
  engage); per-unit `0x_008`=`0x1d` (units engage, `wt_rd=0`). The engage *mechanism* does not determine the weight read.
- **Reframe (kernel patch 0014):** the in-stream broadcast op_en (regcmd `tgt 0x81`/`reg 0x08`) is **not** a PC op_en —
  `tgt 0x81` → base `0xf000`, so it writes `0xf008` = the global RKNPU **ENABLE_MASK** (`0x1d`). So "it restarts the PC"
  (mesa's own `rkt_ml.c` comment, and my reasoning) was wrong; the `ds0_first` 0/-1 swings were a sampler **timing
  confound** (the task finishing before the 1-sample poll), not real latch/no-latch.
- **`enable_mask=0x1d`** (kernel CPU-writes `0xf008` before OP_EN, like the vendor) → **hard hang** (the ENABLE_MASK
  auto-start engages but deadlocks — no completion, no readback).
- **Persistent wall across every run:** `core wt_rd=0` — the CMAC reads **zero** weights from CBUF while the CNA loads
  it (`top wt_rd=3200`). This is the conv0 CBUF→CMAC channel-bank wall, now reached from `conv2d`.

Offline weight-BO compare: mesa's emitted weight BO differs from `vendor-weights.bin` in **97%** of bytes (every `oc`
differs). Inconclusive on its own — a value difference does not explain a *structural* `wt_rd=0`, and `vendor-weights.bin`
may be an imperfect extraction.

**The way out (evidence-based, not more param-spraying).** The load-bearing fact: `replay_rocket` (vendor regcmd +
vendor weights + vendor bias) **computes** on this exact kernel (`wt_rd>0`, real feature map); live mesa — whose regcmd
now matches the vendor's — does not. So the cause is isolable by swapping **one component at a time** on the same
harness while reading **`core wt_rd`** (the structural oracle). The earlier bisection used `distinct` (the invalid
metric), so re-running it with `core wt_rd` is **not** redundant work:
- **Thread A (harness bisection):** `replay_mesa`, regcmd held at vendor-patched, swap weights/bias mesa↔vendor, read
  `core wt_rd` → pins the `wt_rd=0` cause to regcmd vs weights vs bias vs submit.
- **Thread B (offline, no flash):** use the position-encoded captures (`idg_A`: weight = `ky*5+kx+1`) to read mesa's
  actual weight tiling against the vendor's CBUF bank order — decides whether the 97% diff is a real tiling/bank
  mismatch (→ the CMAC reads an empty bank) or extraction noise. `enable_mask` must be left off (it hangs).

## 2026-06-24 — the ruler was broken: it's an empty MAC, not the requant (and the floats below are now in question)

**Reversal, and not a small one.** Everything below this section was measured with `distinct` (how many
different output values come back) as the stand-in for "did it compute". That stand-in does not survive
contact with two facts found today, so the requant/float-surface conclusions below are **suspect for
`conv2d` and have to be re-read with that in mind.**

1. **`distinct`/`head` were never a correctness test.** The output *head* is the same (`d6c4afd8`) whether
   the weights are correct or **shuffled** — provably-wrong input produces the same fingerprint, so the
   fingerprint never read correctness. And a CPU reference of the exact int8 op (plain `numpy`, quant params
   read straight off the `.tflite` — note `parse_tflite.py` reads the quant fields off-by-one; the real layout
   is `min=0/max=1/scale=2/zero_point=3`) shows the **correct** output of `conv2d.tflite` **saturates**: on the
   harness ramp, `acc` runs to ±170000, `M=1.299` pins ~100% of it to `0x7f/0x80`, distinct≈5. The synthetic
   model's `out_sc` is simply too small for its random weights. So on this model a correct conv and a broken
   constant-fill **both** collapse to `distinct≤2` — the metric cannot tell them apart. Months of "make distinct
   big like the vendor's 252" were chasing a target (`252`) that is **not** the correct answer; it is the vendor
   requant running at a 3648× finer scale (shift 26 vs 14), which dodges the saturation. Correct, here, is grey.

2. **Calibrate the model, and the grey turns out to be an empty multiply, not a hot requant.** Patched
   `conv2d.tflite` → `conv2d-cal.tflite` (only `T3`: `out_sc 0.0235→32`, `out_zp 0→128`; weights/bias/inputs
   byte-identical) so the *correct* output is a rich non-saturated map (`distinct~256`, ~1% saturated). On the
   board, mesa's native output is **pinned to `out_zp` (`0x7f/0x80` = 127/128) with no `00`/`ff` tails** → the
   accumulator is ≈0. The chip's own regcmd shows mesa computing OUT_CVT **correctly** for the calibrated model
   (`0x40b0`=32052, `0x40b4`=25, `0x40ac`=0 ⇒ `M=in_sc·wt_sc/32` and `out_zp=128`). Since the MAC is upstream of
   OUT_CVT and independent of `out_sc`/`out_zp` — the only things changed — the **original** model's `distinct=2`
   was **also MAC≈0**, never requant saturation. **The requant is exonerated for `conv2d`.** The coefficients are
   all in DRAM (readbacks real: in 251 / wt 199 / bia 127 distinct) and the engine runs — and the product is zero.

3. **Coherency ruled out, bug localized to four geometry registers.** `replay_rocket` computes (MAC≠0) with the
   vendor regcmd on the *same* kernel, so the NPU reads DRAM fine — MAC=0 is not coherency. Diffing the fresh
   native regcmd against the vendor's, the only config divergences are **four CNA geometry registers** in mesa's
   generic path `fill_regcmd_rk3576_normal` (`rkt_regcmd.c`), calibrated on stride-1/3×3 shapes and wrong for this
   5×5 stride-2 conv: `0x1024` `k_word` hard-codes the kernel size to 3 (`0x0202`, wants `0x0404`); `0x1018`
   (`0x...505`→`0x...404`), `0x1040` CBUF_CON0 (`0x14000000`→`0x10000000`), `0x1080` SURF_STRIDE
   (`0x00000101`→`0x02020101`) — each confirmed against both the vendor capture and the hard-coded conv0 path.

**FIX (applied, NOT yet board-confirmed):** corrected the four formulas in `rkt_regcmd.c`, conditional on
`s==2`/`k≥5` so MobileNet's 1×1 and 3×3-stride-1 layers are untouched; rebuilt `libteflon.so`. The board hangs
after one submit (it always has) and hung before the userspace verdict printed, so **whether this turns the MAC
on is still an open question the board hasn't answered.** Watch the kernel `out task=0 … distinct=` readback: a
real spread off `out_zp` = the geometry fix works; still `0x7f/0x80 distinct=2` = MAC still 0, next lever is the
mesa-only in-stream op_en (`tgt 0x81 reg 0x08`) the vendor doesn't emit.

> **Caveat on the sections below.** The `0x5024` float-surface decode (2026-06-23 late) was done under the
> vendor regcmd, where the MAC *does* run, and judged by `distinct` — so it may describe a real per-axis
> mechanism *or* an artifact of the vendor's finer output scale. For the per-tensor `conv2d` the bug is now
> upstream of all of it (empty MAC / geometry). Kept below as the record, not as a settled conclusion.

## 2026-06-23 (late) — the SDP requant buffer format, cracked from controlled captures

The whole-session bisection had localised the saturation to the **SDP bias/requant buffer**
(`rkt_coefs.c`): with the vendor's buffer the pipeline computes, with Mesa's it saturates, and
**zeroing the `0x5024` "second buffer" alone re-saturates** (`iso-noFloat` → `distinct=2`), so that
region is load-bearing, not padding. Three purpose-built convs were captured on the board to read the
buffer the vendor runtime actually uploads (`dirty/ABC_test/{iso_scale,iso_sum,iso_bias}`, all
conv2d-shaped `16→128 5×5 s2`, each varying exactly one quant axis), plus three position-encoded
captures (`dirty/vendor_cap/idg_{A,B,C}`, weight = `ky*5+kx+1` / `ic+1` / `oc+1`). The per-channel
requant buffer (`bo1[51200:]`) decodes cleanly:

| field | offset | what it is | evidence |
|---|---|---|---|
| **A** | `0` | `int32[128]`, **contiguous** per-channel term ≈ `0x80*(sw+bias)` | `iso_sum`: `A` vs weight-sum **R²=1.0000**; `iso_scale`: slope **127.93 ≈ 0x80**; `iso_bias`: `A` linear in bias |
| **B** | `512` | **one int32 scalar** = `0x80 - wt_zp` | `iso_scale` wt_zp 0 → **128**, `iso_sum` wt_zp 128 → **0**, `iso_bias` wt_zp 129 → **−1** |
| **float surface** | ~`544`+ | **the dequantised weights** (`wt_sc·(q−zp)`), float32, in the HW-tiled weight order | `iso_sum` surface = the model's **±100** values; `idg_A` distinct vals top out at **25 = max(ky·5+kx+1)**; `idg_B` at **16 = max(ic+1)**; `idg_C` encodes **oc+1** |

So the "mystery floats" at `0x5024` are **a second copy of the weights**, dequantised to float32 — the
hardware reads the weights twice (int8 to the CMAC at `0x1110`, float32 to the SDP at `0x5024`). Mesa
writes the int8 copy but leaves the float copy **zero**, which is why every asymmetric layer saturates.

**Mesa's two concrete bugs in `rkt_fill_biases` (RK3576 path):**
1. **Layout.** It writes `[8×i32 A | 8×i16 B | 8×i16 C]` per 64-byte group; the hardware wants a
   *contiguous* `int32[128]` A then a *single* scalar B. The two layouts only coincide for `oc<8`;
   every channel from 8 up reads A out of the wrong slot.
2. **Empty float surface.** The `+0x100` "X2 pad" left zero is actually the dequantised-weight array
   the SDP requires.

The **A-term math** Mesa already has (`0x80*(sw+bias)`) is the right shape — confirmed `R²=1.0` on
`iso_sum`. (The standalone per-**tensor** `conv2d.tflite` capture, `vendor-bias.bin`, is 20800 B with a
*different* shape — an extra `int32[128]` where the per-channel buffer has the scalar B — so the
per-tensor and per-axis encoders differ; MobileNet is per-axis, so the per-channel format above is the
one to implement.) The float surface decodes (confirmed two clean independent ways — `idg_A` is the kernel ramp
`1,2,…,25`; `iso_sum` is the model's `±100` in clean **25-wide (= 5×5 kernel)** blocks; both put
**kernel position innermost**) as the **dequantised weights**. The layout is **fixed-position** (same
offsets for the same conv shape, not a content-sized stream): `A[128]` int32, the `B` scalar + pad,
then a tiled weight region with a **consistent ~124-float dense block** at the same offset in every
capture (idx 256…379), a sparse `....wwww`-period-16 (= `ic`) preamble before it, and a trailing
sparse region. (An earlier "the block grows with the values → compression" read was a measurement
artifact — `iso_sum`'s `±100` simply fills the preamble's otherwise-sparse slots, it is the same
fixed layout.) **Open:** which `(oc,ic,ky,kx)` maps to each slot of that tiled region — the per-axis
order. `idg_B`/`idg_C` read anomalously (values 79.. / 133.. past the `ic+1`/`oc+1` range) so they do
*not* give the `ic`/`oc` order cleanly (possibly stale captures); the tiling has to come from the
NVDLA feature-tile definition or a board write-back test (Mesa controls the `0x5024` base, so a
candidate dense kernel-inner layout can be emitted and checked for de-saturation).

## 2026-06-23 — Harness validated faithful; the bug is the geometry/config, not the data

Two results this day, both first-hand (one on-board, one straight from the deployed source):

**1. `replay_mesa` is a FAITHFUL reproduction (board-validated).** Booted an image whose only
NPU job was the *real* Mesa Teflon `conv2d.tflite` (so the kernel's `audit_arm` cnalive fires on
the genuine Mesa payload, not the replay). The real Mesa path gives the *same* signature as the
`replay_mesa` reconstruction:
- `OUT: distinct=2 (min=7f max=80)` — degenerate, identical to the replay.
- `cnalive: ds0_first=-1`, `CNA G0_DS0=0 G1_DS0=0` — same as the replay.
- And crucially the **operand BOs are all real**: `in distinct=251`, `wt distinct=199`,
  `bia distinct=127`. The inputs/weights/bias are non-degenerate; only the **output** collapses.

So this is **not** a data-degeneracy bug (the coefficients reach DRAM intact) and the `replay_mesa`
harness can be trusted. The defect is in the **command stream / geometry**, surfacing as the engine
producing a constant.

**2. The conv shape is confirmed, and Mesa's geometry encoding for it does not match the vendor.**
`conv2d.tflite` = input `[1,80,80,16]`, weights `[128,5,5,16]`, output `[1,40,40,128]`, 5×5,
**stride 2**. The vendor capture is the *same* op (its BO sizes match exactly: input 80·80·16 =
102400, output 40·40·128 = 204800, weights 128·5·5·16 = 51200), and it dispatches it as **3–4
tasks** split by output-channel.

Mesa's `rkt_task.c` / `rkt_regcmd.c` compute the CNA geometry with **shape-specific hand-tuned
constants** (`input_width==8`, `input_channels==32 && input_width==80`, `input_width==40 &&
input_channels_real==40`, `input_surface_stride=112`, the `input_width>=112 && stride==1`
row-window path, plus a block of `emit_raw()` magic values). This generic `[1,80,80,16]` stride-2
conv matches **none** of those special cases, so it falls to the generic path — and the generic
path emits geometry that diverges from the vendor. Concretely, the deployed source emits
`CNA_DATA_SIZE0 = DATAIN_WIDTH(80)|DATAIN_HEIGHT(80) = 0x00500050`, whereas the vendor capture has
`0x00000190` (W=0, H=400) for the same op. The whole rocket geometry encoder is tuned per-shape and
is incomplete for shapes outside the hand-fitted set — that is the bug class.

**The vendor's CNA geometry decodes to GEMM dimensions (conv-as-matmul).** Matching the
vendor capture's CNA registers to arithmetic of the known conv shape, four fields land exactly:
`DATA_SIZE0` height `0x190 = 400 = ic·kh·kw = 16·5·5` (the **K** / contraction dim — the
im2col gather depth), `DATA_SIZE1` channel `0x7f = 127 = oc-1 = 128-1` (the **N** dim),
`DATA_SIZE2` hi `0x640 = 1600 = ow·oh = 40·40` (the **M** dim), `DATA_SIZE2` lo `0x0f = 15 = ic-1`
and `DATA_SIZE3` `0x4f = 79 = iw-1`. So the RK3576 CNA wants the conv **folded into a GEMM**
(M=1600, N=128, K=400), not the raw spatial `[W,H,C]`. (One field, `DATA_SIZE1` channel_real
`0x404 = 1028`, does not decode cleanly yet.) A 1×1 kernel makes the folding trivial (K=ic), which
is why the pointwise/depthwise MobileNet layers limp by while this 5×5 conv exposes it.

**A regression, and a residual.** An *earlier* Mesa (the stale dump) emitted the **folded** values
(`DATA_SIZE0=0x190`, `DATA_SIZE2=0x0640000f`, `DATA_SIZE3=0x004f004f` — all = vendor; only
channel_real differed, 514 vs 1028). The **current** deployed Mesa has **regressed** to raw spatial
dims (`DATA_SIZE0=0x00500050`, `DATA_SIZE1=0x000f0010`, `DATA_SIZE3=0x640`). So restoring the folded
geometry is a concrete, necessary fix for the current tree. It may not be *sufficient*: a
full-config `replay_mesa` test on the old (folded) dump — op_en/pad stripped, `0x1018/0x1024`,
the OUT_CVT requant and CBUF all patched to the vendor — still saturated (distinct=2, ds0_first=-1).
That test left exactly one config register un-patched: **`DMA_CON2` (0x1080) `SURF_STRIDE`**
(mesa `0x00000101` vs vendor `0x02020101`). So the residual is either that surface stride or the
submit structure itself — the single decisive experiment is `replay_mesa` full-config **plus**
`0x1080 → vendor`.

**`DMA_CON2` patched → still saturates (2026-06-23). The regcmd is now FULLY ruled out.**
Ran exactly that: `replay_mesa` with op_en/pad stripped and `0x1018/0x1024/0x1040/0x40ac/0x40b0/
0x40b4/0x1080` all → vendor — i.e. the command stream byte-identical to the vendor's task0 (only the
address registers differ, pointing at the replay's own BOs). Result: `OUT distinct=2`, `ds0_first=-1`,
live `DATA_SIZE0=0` — **unchanged**. Meanwhile `replay_rocket` (the vendor's *payload* — same regcmd
**and** the vendor's weights/bias BOs — through the same rocket UABI) *computes* (distinct=254). So:

> **The conv2d defect is NOT in the command stream.** A vendor-byte-identical regcmd, submitted by
> Mesa's path, still produces the constant output. The remaining difference between the computing
> `replay_rocket` and the failing `replay_mesa` is the **payload data and submit path**: the
> coefficient BO contents/layout (Mesa packs weights as 204800 B per-tensor; the vendor's regcmd
> expects its own 51200 B per-channel packing at `0x1110`, and the per-channel requant A/B/C buffer
> at `0x5020`/`0x5024`), and possibly the task tiling (Mesa dispatches one task; the vendor tiles
> 3–4). The 300 KB scratch BO (bo02) is **not** referenced by any address register, so it is ruled
> out. Next decisive split: `replay_mesa` + vendor regcmd + **vendor weights + vendor bias** — if it
> computes, the bug is purely Mesa's coefficient encoding (`rkt_coefs.c`); if it still saturates, the
> bug is the submit/tiling path (`rkt_task.c`/`rkt_ml.c`).

**RESOLVED (2026-06-23): the bug is the COEFFICIENT DATA. `replay_mesa` + vendor regcmd +
vendor weights + vendor bias → COMPUTES** (`OUT distinct=98, nonzero=202859/204800`, head
`0a 0b 0b 05` — a real feature map). The only change from the saturating run was swapping Mesa's
weights/bias BOs for the vendor's. Therefore:

> The conv2d defect is **entirely in Mesa's coefficient (weights + bias/requant) encoding**
> (`rkt_coefs.c`). The command stream is fine (vendor regcmd used either way), and **Mesa's single-task
> submit path is fine** — it computes the whole conv (99% nonzero) when fed the vendor's coefficients.
>
> Two artifacts are now retired: (1) `ds0_first=-1` is a **timing artifact**, not a geometry-latch
> failure — this run *computed* with `ds0_first=-1` (the single task finishes before the kernel's
> 4000-sample poll catches `DATA_SIZE0` non-zero); trust the OUTPUT distinct, not `ds0_first`.
> (2) the "geometry not latching / conv0 wall" framing is moot — geometry latches fine; the engine
> was running on mis-encoded coefficients.

Next: isolate **weights vs bias/requant** (one swap at a time). My own note added to the driver
(`rkt_ml.c:348-364`) flags the per-channel requant buffer as the suspect/TODO, and the weight
*packing order* was already shown to match the vendor — so the bias/requant A·B·C buffer
(`0x5020`/`0x5024`, per-tensor in Mesa vs per-channel in the vendor) is the leading candidate.

**ISOLATED to the BIAS/REQUANT buffer (2026-06-23).** `replay_mesa` with the full vendor
regcmd and **Mesa's own weights** but the **vendor bias buffer** (`MESA_BIAS` = bo1[51200:72000])
→ **COMPUTES, `OUT distinct=252`** (an even cleaner feature map than the all-vendor run). So:

> Mesa's **weight encoding is correct** (packing order + quantization both fine); the entire
> conv2d defect is the **per-channel requant / bias buffer** at the weight-BO tail (regcmd
> `0x5020` → A·B·C, `0x5024` → the second per-channel array). Mesa writes it per-tensor; the
> vendor writes it per-channel. Swapping *only* that buffer to the vendor's makes the conv
> compute. **This is exactly the per-channel-requant TODO I noted in `rkt_ml.c:348-364`** — upstream
> doesn't attempt it (it gates per-axis quant out as "not supported"); this note is my own. The fix
> lives in `rkt_coefs.c` (the bias/requant emit), and nothing else needs to change.

The remaining work is purely to decode the vendor's per-channel requant buffer
(`vendor-bias.bin` = bo1[51200:72000], now a *known-good* reference because it computes) into a
formula over the conv's quant params + per-output-channel weight sums, and emit it from
`rkt_coefs.c`.

**The "A" term: formula structure confirmed; the scale is the remaining piece (2026-06-23).**
Decoded the vendor 0x5020 buffer as the `[8×i32 A | 8×i16 B | 8×i16 C]`-per-8-oc layout (Mesa's
assumed layout — confirmed; a flat layout decodes to garbage). Offline-fit the vendor's per-channel
`A` against the conv quantities: **`vendor_A = -M · (bias_q - in_zp·sw)`, k = -1.3155 ≈ -M (=-1.299),
R² = 0.991** over all 128 channels (`M = in_sc·wt_sc/out_sc`). So the per-channel offset is
**structurally `A ∝ (in_zp·sw - bias_q)`** — Mesa's `A = 0x80·(sw + bias)` has the wrong sign on the
weight-sum term, omits the `in_zp` factor, and is scaled by `0x80` instead of `M`. (`B`,`C`, and the
0x5024 float array did *not* fit the per-tensor quantities, R²<0.07 — they carry the vendor's
**per-channel weight re-quantization**, which a per-tensor Mesa path doesn't need to reproduce.)

The blocker is the **scale/shift**, not the formula: a board test that fixed only `A` (keeping
Mesa's `OUT_CVT` shift=14) saturated *identically to baseline* (`80 80 7f 7f`) — at shift=14 the
output clips regardless of `A`, because the vendor runs the whole SDP `2^12` hotter (shift=26 vs 14;
its `A` is pre-multiplied by `M`, i.e. `vendor_A = M·(in_zp·sw - bias)` in output units, brought back
down by the larger shift). So the correct Mesa emit is `A = in_zp·sw - bias_q` with the SDP scaled
the vendor's way (shift≈26 and the matching `A`/`B`/`C` scale), **not** Mesa's current shift=14 +
`0x80·A`. Pinning the exact shift/scale constants is the last step (needs the SDP scale semantics or
a couple of focused board runs).

**The exact fixed-point scale is NOT cleanly derivable from arithmetic (2026-06-23).** Tested the
corrected-sign `A = in_zp·sw - bias` (constant `B = 0x80-wt_zp`, `C = 0x4000`, `0x5024` zeroed) at
both shifts: shift=14 saturated *identically to baseline* (`distinct=2`, `7f 7f 80 80`) — at that
scale the `A` buffer has no effect at all, the overall output simply clips; shift=26 moved it only
from 2→3 distinct (still `7f 7f 80 80`, not a feature map). The vendor's buffer computes at shift=26
because of its **per-channel `B`, `C`, and the `0x5024` float array** — which carry the SDP scale,
and which I set to constants/zeros. Those did *not* fit the per-tensor quantities (R²<0.07), and the
fixed-point datapath (how `A`·`B`·`C`·`BS_MUL`·`OUT_CVT` combine bit-for-bit) is not recoverable
from the known-good buffer + the quant params alone — every fixed-point model tried (shift=14 direct,
shift=26 raw) was wrong on the board. So the *structure* is settled (bug = the bias/requant buffer;
`A ∝ in_zp·sw - bias`, R²=0.99) and is upstreamable as-is (this is the per-channel-requant TODO I
left in `rkt_ml.c`; upstream gates per-axis out rather than attempting it), but the
exact scale constants need the RK3576 SDP datapath spec (the per-channel `BS_MUL`/`OUT_CVT` fixed-point
semantics), not further blind arithmetic. That is the clean handoff line.

**The requant is TWO per-channel BS surfaces; Mesa leaves the second one zero (2026-06-23).**
The DPU bias is read by `DPU_RDMA` from *two* surfaces: `0x5020` (`RDMA_BS_BASE_ADDR`) holds the
`[A|B|C]` int table, and `0x5024` (the "second buffer") holds a per-channel **float32** array. Both
are essential — board isolation, vendor weights, vendor regcmd, shift=26:

- `A` alone (vendor's exact `A`, `B`/`C`/floats zeroed) → `distinct=1` (constant = the OUT_CVT
  offset). The bias-add alone carries nothing.
- `A`/`B`/`C` kept, the `0x5024` floats zeroed → `distinct=2` (degenerate).
- The full vendor buffer (both surfaces) → `distinct=252` (computes).

So the `0x5024` float surface is required, and **Mesa never writes it**: `rkt_fill_biases` allocates
`groups*64 + 0x100` and points `0x5024` at `bias_addr + 0x400`, which lands in the zeroed `0x100`
pad. That zero second-surface is a concrete part of the bug. The float array decodes to a per-channel
table (`float[0] = -wt_sc`, then 128 varied per-channel floats — *not* the per-channel weight scales,
not any clean function of the per-tensor quant params). It is produced by the vendor toolkit's
per-channel quantiser, which lives in the compiled `librknnc.so` (rknn-toolkit2 2.3.2) — not in
readable Python and not recoverable by swapping/fitting (proven exhaustively: A-alone, A+B/C-no-float,
and every fixed-point model all fail on the board).

**Net:** the conv2d defect is fully cornered — it is the per-channel SDP requant, two BS surfaces
(`0x5020` int `[A|B|C]` + `0x5024` float), of which Mesa writes only the first and gets the `A`-term
wrong. The `A`-term is solved (`A ∝ in_zp·sw - bias`, R²=0.99). The remaining per-channel `B`/`C` +
float surface are the vendor toolkit's per-channel re-quantisation and need the RK3576 SDP datapath
semantics (how the int and float surfaces combine in the converter) — i.e. the per-channel requant
TODO I noted in `rkt_ml.c` (upstream doesn't attempt it), now with the exact surfaces and the A-term
pinned. That is the real handoff: a feature
(per-channel requant + the second BS surface), not a value left to guess.

**Honest caveat / next step.** The earlier register-level diff used a *stale* `mesa-regcmd` dump
(captured from a pre-2026-06-16 Mesa; the deployed lib is 2026-06-19 and its geometry code differs,
e.g. `0x1018` is now hard-coded to `0x40000404`). To pin the exact current divergence, the next
board run must take a **fresh** regcmd dump from the *deployed* Mesa and diff it against the vendor
capture (the only fixed reference), then trace each divergent CNA register back to the
`rkt_task.c` computation. Single submit, low crash risk.

## Symptom (precise)

- Full graph runs end-to-end: no IOMMU fault, no PC timeout (on the GPLL clock), every layer
  reads its own real feature data from DRAM (bandwidth counters confirm the CNA pulls the whole
  input + weights into the CBUF).
- The **CMAC reads ~0 out of the (correctly loaded) CBUF**: `core[wt_rd=0, dt_rd≈0]`, writes a
  degenerate output (`dt_wr` = a fraction of the full volume). conv0 output is `distinct=2`
  (min=0x7f, max=0x80) — i.e. ±(one constant), not a feature map.
- No per-unit completion ever fires (`INTERRUPT_RAW_STATUS` FEAT/WT/CSC/CORE/DPU all 0); only the
  PC asserts done, and it does so ~1 µs after OP_EN (`samples=1`) — a hollow, instant "done".

### The whole bug, pinned to one counter (2026-06-21)

A counter-level read of conv0 isolates it past any doubt — everything upstream of the CMAC weight
read is confirmed correct, and the failure is a single zero:

- `top[dt_rd=9408×16 = 150528]` = the **full** 224×224×3 input is DMA'd from DRAM into the CBUF.
- `top[wt_rd=96×16 = 1536]` = the conv0 weights are DMA'd into the CBUF, in the **RK3576-specific
  first-conv (ARGB) pack** (ky-major, 1536 B — board-derived; the RK3588 pack is a known wrong path).
- The CBUF SRAM readback (`@0x3fe80000`) shows the data region staged (`@0x0 d164/nz717`) and the
  weight blocks the vendor's `cache_sgt` defines (`@0xe0000/0xf0000`) holding dense packed weights.
- `0x3018=0x10000081` (first-conv mode 0x81), the per-channel weight zero-points (`0x1054/58/5c =
  0xffffff80`) and every CNA/CORE weight register are byte-identical to the vendor; the executers
  engage (`exec_ever=0xf`).
- **And still `core wt_rd = 0`** — the CMAC reads none of the loaded, correctly-formatted weights.
  Weightless MACs → zero-point → the DPU writes a fixed 2-channel (`dt_wr=25088`) degenerate output,
  which starves every downstream layer (they then read `top[…=0]` and repeat the same 25088).

So the bug is **not** staging, format, banks, mode, or any command-stream value — it is solely the
CNA-weight-subunit → CMAC weight-read handoff: the weight-load-done that should kick the CMAC's CBUF
read never asserts (matching the dead WT/CSC interrupt). One latch, no register window.

### Single-op isolation (2026-06-21, Tomeu's method) — 2 of 3 suspects cleared

Reproduced on the **simplest standalone conv** (Mesa's own `conv2d.tflite`, 5x5, 16→128, nothing to
do with mobilenet): NPU output `distinct=2`, CPU output a real feature map. So the bug is **per-op,
not whole-graph**, and it affects a **normal** conv, not just the first-conv. Tomeu's three suspects:

- **coefficients BO — ruled out.** `ROCKET_DEBUG=dump_bos`: Mesa's encoded weights are varied
  (distinct=241), same value range as the tflite, just NVDLA-repacked (51200→204800 + padding).
- **input BO — ruled out.** PRE/POST CBUF SRAM dump: the input feature ramp stages in cleanly
  (`@0x0` goes from garbage to the known ramp `80 81 82 …`).
- **a kernel-side write — the remaining suspect.** Weights are DMA'd from DRAM (`top wt_rd=3200`) but
  the weight blocks (`@0xe0000/@0xf0000`) read **byte-identical PRE and POST** and `core wt_rd=0`:
  the weights are read but never deposited into the CBUF weight bank.

Tried staging weights into the on-chip SRAM + repointing the CNA weight source (0x1110) to it (fix
#1 at an arbitrary IOVA, fix #2 at the vendor's exact NBUF window 0xffff8000) — neither moved
`core wt_rd`, so the weight *source location* is not the lever. The one structural gap vs the vendor:
it places all BOs (incl. weights) in the on-chip **NBUF** (the `rk3576_cache_sgt_init` setup rocket
lacks); rocket uses DRAM. Open question to Tomeu (flipper #55): what arms the CNA weight-load deposit
into the CBUF on RK3576 — the NBUF residency, or a kernel register write.

### conv2d payload diff: operands vs Mesa (2026-06-21, Tomeu's ask)

Dumped the full BO payload (weights/input/bias/output) the **vendor** stack hands the hardware for a
standalone 16→128 5×5 conv and laid it next to **Mesa's**, both running the *same* conv (the vendor
`.rknn` rebuilt from Mesa's own `conv2d.tflite` weights) fed the *same* ramp input. Vendor side:
instrumented `rknpu_job.c` to translate the regcmd's BO addresses (0x1088 input / 0x1110 weights /
0x4018 output / 0x5020 bias) through the IOMMU and print the bytes; Mesa side: `ROCKET_DEBUG=dump_bos`.
Both emitted over the serial console as text (`rknpu cap:` / `mesa cap:`) and diffed with
`vendor-capture/diff_payload.py`. Mechanism check: the vendor **input** BO reads back the exact ramp
fed → the dump reads the right memory, not neighbouring garbage.

- **weights** — dense and varied on both (~99% nonzero; distinct 256 vendor / 221 mesa). Mesa's
  coefficient BO is **not** degenerate.
- **input** — the same ramp on both (staging equivalent).
- **bias** — populated on both.
- **output** — the only divergent buffer: Mesa's computed output is degenerate (`distinct=2`). The
  vendor output was caught at submit (pre-compute), so the *computed* results aren't compared here.

What it establishes / what it does **not**: it rules out "Mesa hands the engine empty or zeroed
operands" — they are well-formed. It does **not** separate a weight **packing-order** defect (right
values, wrong layout → the CMAC reads them as noise) from a pure **execution** defect: the two
toolchains quantize independently, so the weight bytes differ everywhere and the packing *order* can't
be byte-compared. Both defects produce the identical signature (dense weight BO + degenerate output).
Consistent with the `core wt_rd=0` CBUF→CMAC localization, **not proof** of it. Open lever: get the
vendor toolkit to ingest the exact tflite int8 weights (it rejects `load_tflite` on arm64) for a
byte-identical layout diff — handed back to Tomeu.

### Faithful payload replay through the vendor UABI — it computes (2026-06-22)

The diff above caught the vendor output *pre-compute*. The fix: capture librknnrt's **entire**
submission and replay those same bytes through the vendor `rknpu` DRM render node, so the *computed*
result is observable. An `LD_PRELOAD` shim (`vendor-capture/capture.c`) records every BO librknnrt
creates and, on the first `SUBMIT`, maps each itself and dumps the content + the raw submit struct.
The standalone conv turns out to be **5 BOs over 3 tiled tasks** (a 4 KiB task-array, a 76 KiB
weights+bias+3-regcmd BO, a 300 KiB scratch, the input, the output), not the single regcmd a naive
replay assumed. `replay.c` re-creates those BOs (same order/size → same deterministic IOVAs, so the
address-remap is a no-op as the first job), loads the bytes, and submits.

Result: the replayed conv produces a **non-degenerate output** — `distinct=254`, `202547 / 204800`
nonzero — written by the NPU into an output buffer the capture confirms was **all-zero** at submit.
This is the first time the captured payload has computed a real result on this bench, and the
control Tomeu's method needs: **the captured bytes + the vendor kernel are sound** — the payload was
never the defect.

The decisive variable was **not** in any BO or the regcmd — it was the submit struct's
`subcore_task[5]` array, which an ioctl *type* trace can't see. librknnrt splits the 3 tiled tasks
across subcore slots — `subcore[0]={start 0, num 1}`, `[1]={1,1}`, `[2]={-1,1}` (`task_counter=0`,
`core_mask=0` AUTO). A hand-built submit that instead put all three on one slot (`subcore0={0,3}`)
ran **task 0 then stalled task 0→1** — `INT_RAW_STATUS=0x30000000`, never the `0x300` the kernel
waits for — i.e. it reproduces the long-standing "PC stalls task0→1" wall exactly. So that wall is a
**dispatch artifact** (one multi-task dispatch the PC won't iterate), not the payload: split into
single-task dispatches and the identical bytes compute. Soft-reset (vendor never issues one) and an
explicit `POWER_ON` (the submit ioctl already `power_get`s via its wrapper macro) were both ruled out
along the way. Tooling tracked in `replay/` + `vendor-capture/`.

**Next:** replay the *same* captured bytes through the **rocket** UABI (`/dev/accel/accel0`). If it
also computes, the rocket kernel is sound and the divergence is in Mesa's payload generation; if it
diverges on identical bytes, the defect is isolated to the rocket kernel driver. The mainline rocket
job model ("all tasks in one job run sequentially on the same core") vs the vendor's per-task subcore
split is the lead to test.

### Same bytes through the rocket UABI — it computes too; the bug is Mesa's payload (2026-06-22)

`replay_rocket.c` re-creates the four data BOs through the rocket UABI (`CREATE_BO` returns each
one's rocket-assigned NPU IOVA), remaps every captured IOVA the regcmd references to those new
addresses (the cross-UABI step the same-IOVA vendor replay didn't need), and submits each tiled task
as its own one-task job (`DRM_ROCKET_SUBMIT`, the vendor's per-subcore split). The rocket kernel
points the PC at the task's regcmd and pulses `OPERATION_ENABLE` itself, so the vendor regcmd (which
folds `op_en` into the submit header rather than appending the broadcast entry Mesa does) runs as-is.

Result: rocket computes the captured payload — output `distinct=254`, `202547/204800` nonzero, head
`07 0e 09 04`, **byte-statistics identical to the rknn replay**, into a verified-zero output buffer.
And in the *same boot*, Mesa's own conv on the same NPU stays degenerate (`distinct=2`). Repeated
under both firmwares to kill the BL31/OP-TEE variable:

| payload \ SPI firmware | vendor (Rockchip TF-A + OP-TEE) | mainline (TF-A v2.14.0, no OP-TEE) |
|---|---|---|
| **vendor** (replay_rocket, captured bytes) | COMPUTES | COMPUTES |
| **Mesa** (its own encoded payload)         | degenerate | degenerate |

The captured bytes compute through *both* UABIs under *both* firmwares; Mesa's payload degenerates
under both. So the defect is **not** the rocket kernel, **not** the hardware/CBUF, **not** the
firmware — it is isolated to **what Mesa encodes**: the coefficient (weights+bias) BO. (One aside:
the rocket multi-task-per-job path NULL-derefs — `replay_rocket` runs one task per job, the shape
Mesa uses anyway.) `replay_rocket.c` tracked in `replay/`.

### It is per-channel weight quantization, NOT packing order (2026-06-22, correction)

A first read of the above guessed the coefficient defect was the weight **packing order**. Decoding
the layout proved that wrong. Position-encoded convs (`vendor-capture/gen_id_generic.py`: three
16→128 5×5 models with `w = ky*5+kx+1` / `ic+1` / `oc+1`) were converted to `.rknn`; the vendor
toolkit packs the weights into the `.rknn` at build time, so the packed buffer is extractable on the
**host** (the min-distinct 51200-byte window — no board flash). Decoded nesting, outer→inner:
`oc1(/32) → ky → kx → oc2(0..31) → ic` — which **matches Mesa's generic `rkt_fill_weights` 100%**.
Packing order is not the bug.

The real difference is the **quantization**. `conv2d_rk3576.rknn` is built `do_quantization=False`, so
it carries the *same* source int8 weights as Mesa; byte-comparing the vendor's packed weights against
the source (in the now-known order) shows each output channel is a **per-oc affine** of the source —
`|corr| = 1.000` for all 128 channels, slopes spanning **1.07–1.67×**. The vendor quantizes weights
**per output channel**; Mesa uses one **per-tensor** `weight_tensor->scale` (`rkt_regcmd.c:334` → a
single OUT_CVT scale/shift at DPU `0x40b0`/`0x40b4`; the `rkt_coefs.c:411` hardcoded-scale list is
the non-RK3576 path). The vendor's SDP requant is itself **per-channel**: regcmd `0x5020` →
`bo01[51200:52224]` is a 1024-byte struct of 16 groups ×`[8×i32 A | 8×i16 B | 8×i16 C]`, and A, B, C
all vary per channel (B correlates −0.98 with the per-oc stored-weight sum; A carries a scale term
plus a bias term). Mesa's RK3576 bias path treats B as the per-**layer** constant `0x80 − wt_zp`.

So: **the RK3576 NPU expects per-output-channel weight quantization (and a per-channel SDP requant
buffer); Mesa emits per-tensor.** This is consistent with — and likely the same root cause as — conv0's
"~2 of 32 channels" channel-bank truncation: per-tensor quant scales every channel by the global max,
crushing the small-magnitude channels toward zero. Open: the exact A/B/C formulas (per-channel
scale-mult / shift / zero-point compensation) — to be cracked with single-variable isolation captures
(vary bias-only / scale-only / zp-only per channel, extract from the `.rknn`, fit), then implement
per-channel weight quant + the per-channel requant buffer in Mesa. Tooling:
`vendor-capture/{gen_id_generic,gen_id_bias,decode_generic,abc_locate,convert_onnx_pt}.py`.

### Bisection in a controllable harness: conv2d is the geometry-latch wall, and the in-stream op_en blocks the latch (2026-06-23)

The per-channel requant above is real for the per-**axis** MobileNet layers, but it is a red herring
for the standalone `conv2d` test: that `.tflite` is per-**tensor** (weights scale 3.912/zp 133, output
scale 0.0235/**zp 0**), and Mesa's requant (OUT_CVT shift 14, out_zp 0) is *correct* for it — the vendor's
shift 26 / zp 137 is just the vendor toolkit's own per-channel re-quantization, a different valid scheme.
What actually fails conv2d was found by reproducing it in a controllable harness rather than by
reasoning: `replay/replay_mesa.c` feeds Mesa's own dumped regcmd/weights/biases back through the rocket
UABI as one task (re-pointing the address regs), with env knobs to swap a single component for the
vendor's. Baseline reproduced the grey (`distinct=2`); swapping the **requant**, the **CBUF** `0x1040`,
and the **weights** each left it grey. None of the quantisation theory moved it.

It looked at first like a geometry-latch failure (the CNA ping-pong groups read the `pp_state_init`
default `DS0=0`/`DS1=0x80000000`), and an earlier draft here claimed the appended in-stream op_en
(`tgt=0x81 reg=0x08 val=0x1d`, the ENABLE_MASK, which the vendor folds into the submit instead) blocks
the latch — removing it flips `G0_DS0` `0→0x190` and `DS1` `default→0x0202007f`. **That read was a
measurement artifact and is retracted.** The `DS0`/`DS1` dump is taken *after* execution, and it
correlates perfectly with whether the engine *ran*, not whether the geometry committed: every variant
that engaged (`dt_wr=12800`) reads the default (the run consumes/resets the group), every variant that
did NOT engage (`dt_wr=0`) reads the real value (it sits un-consumed). So "geometry latched" was mostly
tracking "engine didn't run."

The less-confounded signal is the *during-execution* `cnalive` sample (`ds0_first`): the vendor
(computes) shows `ds0_first=0` (geometry present), Mesa baseline (saturates) shows `ds0_first=-1`
(geometry never present) — so Mesa baseline does genuinely run on an empty shape. Stripping op_en **and**
the 4 trailing `(0,0,0)` pad entries **and** patching `0x1018`/`0x1024` makes the regcmd's *structure*
(its set of entries) match the vendor's, and it *still* saturates (`distinct=2`, `dt_wr=12800`) when run
— so the regcmd **structure** (op_en / padding / geometry words) is not the bug. But that config did
**not** patch the OUT_CVT requant words (`0x40ac`/`0x40b0`/`0x40b4`) or CBUF `0x1040` to the vendor's, so
the regcmd was **not** byte-identical — those *values* still differ, and Mesa's `0x40b4` shift = 14 vs the
vendor's 26 is exactly the signature of a requant run **~2^12 too hot → clamp to 0/255 = the saturation
seen**. So the live suspects are now (1) the **OUT_CVT requant values** in the regcmd, and (2) the
**coefficient data** (weights/bias) — reviving the requant/bias direction the per-tensor argument had set
aside; the geometry/op_en/structure path is closed. (Also learned: the 4 trailing pad entries are not
junk — with op_en removed they buy ping-pong handoff time.) **Decisive next:** `replay_mesa` with op_en+pad
stripped **and** the OUT_CVT (`0x40ac=9`/`0x40b0=0x5d58`/`0x40b4=26`) patched to the vendor's — does the
saturation clear? then swap the weights/bias. (Capture `cnalive ds0_first` alongside.) (The instrumented
rocket kernel is fragile — a `drm_mm_takedown` NULL-deref crashes BO cleanup after ~2–3 submits, an
invalid OP_EN wedges the NPU — so each boot yields one or two submits before a power-cycle; key variant
first.)

## Confirmed byte-identical to the vendor

Verified on the board with an automated register-by-register diff against a live vendor capture
(instrumented `rknpu`, real IOMMU addresses):

- **conv0 regcmd**: 138/138 non-address CNA/CORE/DPU/RDMA entries match. The only delta is the
  broadcast `op_en` word rocket appends (`tgt=0x81 reg=0x08 val=0x1d`) where the vendor folds the
  same value into its submit header `enable_mask`.
- **Kernel submit** matches `rknpu_job_subcore_commit_pc` register-for-register: `PC_DATA_ADDR`,
  `PC_DATA_AMOUNT` (same formula → 71), `INT_MASK`/`INT_CLEAR` = 0x300, `PC_TASK_CONTROL` =
  `(0x7<<16)|1`, `PC_DMA_BASE` = 0, the `OP_EN` 1→0 pulse, and the `PC_DATA_ADDR=1` pre-write.
- CBUF geometry (16 banks × 512 × 128 B = 1 MiB), `state_init` (0x1004/0x1024/0x1e), the full
  soft-reset (srst_a + both CBUF resets) + IOMMU re-attach, the clocks-on set — all match.

## Ruled out (each tested on hardware)

| Hypothesis | Result |
|---|---|
| regcmd content / values | byte-identical to vendor (above) |
| submit/kick sequence | identical to `commit_pc` |
| ping-pong producer/consumer group mismatch | swept `geom_both` (geometry into BOTH groups) + cpu_replay + per-job pp_state_init + per-job CBUF reset + fixed S_POINTER, 14 combinations — all degenerate |
| op_en mechanism / broadcast value (0x1d vs 0x7f) | no change |
| dual power domain (PD_NPU0 + PD_NPU1) | added multi-PD attach (`dev_pm_domain_attach_list`) — no change |
| NPU_GRF URGENT QoS | set sel=1 — no change |
| DDR contention | 6-core hog + urgent — no change |
| readback-too-early / cache coherency | dual-path (cached vs MEMREMAP_WC) readback; delay — no change |
| IOMMU faults / stale TLB | none; rk_iommu has no `.flush_iotlb_all` |
| clock **rate** (GPLL 198 MHz … 786 MHz) | no change |
| clock **source** PVTPLL (see below) | makes it worse — 0 jobs complete |
| **submit-time timing race** (pure busy-wait 1 µs–1 ms before OP_EN, swept ×20 runs) | **no change** — conv0 writes exactly 2 of 32 channels (`core dt_wr`=25088) every run, every delay |
| per-job ping-pong pointer advance (`double_kick` warmup pulse) | no change — same flat 2 channels |

## Clock-ID finding (useful, upstreamable) and the PVTPLL dead end

The vendor sources the compute clock `CLK_RKNN_DSU0` via **SCMI** (TF-A → PVTPLL); mainline routes
it via `&cru` (fixed PLLs). `aclk_rknn0` and `aclk_rknn_cbuf` are bare gates off DSU0, so CBUF and
compute share one clock — they cannot be decoupled, on either driver.

Routing rocket's `npu` clock to `<&scmi_clk CLK_RKNN_DSU0>` silently no-ops: **the kernel CRU
binding numbers the clock 232, but our TF-A `clock_table` keys it at 238.** `<&scmi_clk 238>` is
settable (rate reads back). But on PVTPLL — correct index, correct rate, OPP voltage raised first
(800 MHz needs 800 mV), rate-set moved after the soft-reset — the NPU completes **0 jobs** (~83
`drm_sched` timeouts / 90 s). PVTPLL needs the full vendor stack (per-chip leakage cal via nvmem +
OPP/devfreq governor) to be a usable clock; the GPLL path at least runs and computes its wrong
answer. The clock theory (that the failure is a timing race) was never testable — PVTPLL never ran
cleanly. Reverted to GPLL.

## Localization / the open question

The gap is the on-chip **CBUF → CMAC** hand-off, the one place with no register window: the CNA
stages the full operands in (bandwidth counters prove it), the vendor's identical command stream
then computes, and rocket's identical stream reads zero. Nothing pollable distinguishes the two.

The truncation is **deterministic within a power cycle**, not a race: a 20-run × 5-point sweep of a
pure pre-kick busy-wait (1 µs–1 ms) and a ping-pong pointer advance both left conv0 at exactly 2 of
32 output channels every run (0 full-channel results in ~1000 jobs). A submit-time read-too-early or
ping-pong race would vary and respond to delay; this does neither — the cut is locked *before* the
job, in the CBUF power-up/reset state, which reads as a channel-bank truncation rather than a timing
race. (An external NVDLA bring-up engineer independently called this "a race below observability";
the sweep is the clean refutation of that for the submit window.)

**What would crack it:** an NVDLA-derived microarchitecture reference for the RK3576 CBUF/CMAC, or
a register-write trace from a *working* RK3588 rocket run to diff the execution (not just the
command stream) against, or silicon-level visibility. This is past what black-box probing from the
mainline driver + DT + as-flashed firmware can reach.

A sister-chip bring-up (RK3568, mainline rocket) is stuck at the same class of wall, a stage
earlier (engage), which suggests one real SoC-family issue, not ten imagined ones —
see https://github.com/gahingwoo/linux-rk3576-npu/issues/1.

## Off-board structural map of the SDP coefficient buffer (2026-06-25, no board)

Done entirely on the host (aarch64) from the one live capture we already have on disk —
`dirty/npu-test/vendor-bias.bin` (20800 B, vendor stack running `conv2d.tflite`) — plus
conv2d's known int8 weights/bias/quant. Reusable check: `vendor-capture/ana_coef.py`.

- **Buffer = `[ABC | float surface]`.** ABC = 16 groups × 64 B (8 oc/group): `A[oc]` int32 @0,
  `B[oc]` i16 @32, `C[oc]` i16 @48. Float surface = the remaining 4944 f32; every nonzero value
  is an integer multiple of `wt_sc`.
- **`A` is derivable.** `A[oc] = -M·(bias[oc] - in_zp·sw[oc])`, `M = in_sc·wt_sc/out_sc`,
  `sw[oc] = Σ(wq-wt_zp)` — corr **-0.996**. A is the per-channel requant **bias-correction** term.
- **`C` varies per output channel (10489–16384, 57 distinct over 128 oc) — for a *per-tensor*
  conv.** A genuine per-tensor requant would emit ONE constant multiplier. Varying `C` means the
  **vendor toolkit silently re-quantises the per-tensor conv into a per-channel one** with
  compiler-chosen scales. That is the *mechanism* behind "blob-only": the float surface is
  per-channel **re**-quantised weights, and the chosen per-channel scales are toolkit-internal.
  A genuinely **per-axis** model (MobileNet) carries explicit per-channel scales, so there the
  same surface is derivable. (Confirms the earlier per-tensor/per-axis split from first principles.)
- **The `.rknn` does NOT carry the assembled live surface.** Live float surface vs
  `conv2d_rk3576.rknn`@33488: **14/4944** floats match — the earlier "match" was a 16-float
  signature coincidence. librknnrt assembles the surface at runtime. ⇒ the surface's exact bytes
  and its **layout cannot be obtained off-board from any .rknn**; only a live (board) capture has it.
- **The surface layout ≠ the weight-DMA layout** (`dirty/vendor_cap/generic_slot_map.npy`):
  among the surface's 742 nonzero slots, **0** match the weight order. It is its own sparse/padded
  layout.
- **Host toolkit limit:** on arm64 `rknn.load_tflite` is unsupported ("unsupported tflite on arm64
  platform"); only the ONNX path converts. And since the .rknn lacks the live surface anyway,
  cracking the per-axis surface layout requires a **board capture of a per-axis conv**, not more
  host conversions.

**Net:** the *derivable* half of the buffer (A = bias-correction × M) is now pinned off-board; the
non-derivable half (per-channel `C` scaling + the float-surface layout) is confirmed to need a live
per-axis capture. The decisive next board step is to capture the vendor's coefficient buffer for a
**per-axis** conv (or for `conv2d-cal`), then feed it verbatim and read maxdiff — no derivation guesswork.

## Clean per-axis board captures (2026-06-25): float surface ≠ weights, but the requant (ABC) IS derivable

Captured the vendor's live coefficient buffer for three **position-encoded** per-axis convs (so the
weights spell out their own coordinates) + per-tensor `conv2d` for contrast, through the vendor rknn
stack (`vendor-capture/{gen_perax,run-coefcap}.py`, full BO dump, coef offset read from the regcmd's
`0x5020`/`0x5024` IOVAs — not guessed). Models: `pw_ic` (1×1, weight[oc,ic]=ic+1), `pw_oc`
(weight=oc+1), `dw_k` (3×3 depthwise, weight=ky*3+kx+1). Decoder: `vendor-capture/ana_perax.py`.

**The float surface (0x5024) is NOT the dequantised weights — not even for per-axis.** Decisive: `pw_oc`
weights are `oc+1`, so a weight copy would show the 128 constants `1..128`; the float surface has **8
distinct values** total (`{-2.25, 0.0078, 0.016, 0.024, 2, 22, 219}`). `dw_k` (weights `1..9`) gives
**384** continuous values, nothing like `1..9`. This **refutes the premise of the per-axis pivot**
(the earlier "the per-channel float surface decodes cleanly to the dequantised weights" — that idg read
was muddled). The float surface is a toolkit-internal structure for per-axis too; its role/derivability
is still open (values look like `in_sc`-multiples / requant terms, but it is not 128 per-channel scales).

**But the ABC requant block (0x5020) is fully derivable for per-axis** — read with the exact offset:
- `A[oc] = M·(in_zp·sw[oc] − bias[oc])` (the bias-correction; constant in these bias=0 / uniform-sw
  models, matching the per-tensor corr −0.996).
- `B[oc] = in_zp − wt_zp = 128` (constant).
- `C[oc]` = the **per-channel requant multiplier, ∝ `in_sc·wt_sc[oc]/out_sc`**: proven by `pw_oc`,
  where `C = 128·(oc+1)` tracks the per-channel weight scale *exactly* (the channel with twice the
  scale gets twice the multiplier), vs `pw_ic` where every channel shares a scale → `C = 16384`
  constant. Derivable straight from the model's per-channel scales.

This also **explains the old per-tensor "C is a blob"**: for a per-tensor conv the toolkit *invents*
per-channel scales (not in the model) → not derivable; a per-axis model *carries* them → `C` derivable.
So the per-axis pivot was right about the **requant** layer (ABC encodable in `rkt_coefs.c`), and wrong
about the **float surface** (not the weights). NEXT: encode the derivable ABC, board-test whether
ABC-alone computes for a per-axis conv (maxdiff) — i.e. whether the float surface is even load-bearing
there — before spending more on the surface.

## Per-axis ABC encoder VALIDATED byte-exact against board ground truth (2026-06-25 pm)

From the clean position-encoded captures, read the per-channel multiplier with the exact regcmd offset
and validated the full ABC against the captured bytes (`pw_oc`, `pw_ic`):

- **A[oc] = 0x80·(Σ_kernel wq[oc] + bias[oc])** — byte-exact. pw_oc: Σwq=16·255=4080 → A=0x80·4080=522240 confirmed;
  pw_ic: Σwq=2167 → A=0x80·2167=277376 confirmed. This is **mesa's current formula** (rkt_coefs.c:423) — A was right.
- **B[oc] = 0x80 − wt_zp** — constant, mesa already correct.
- **C[oc] = round(2^14 · wt_sc[oc] / max_oc(wt_sc))** — the per-channel requant multiplier. Validated
  **256/256 exact** across pw_oc+pw_ic (`wt_sc[oc]=max|w[oc]|/127`). C is *relative* (normalised to the
  max channel = 2^14); the absolute scale rides the per-layer OUT_CVT shift mesa already computes.

So the per-axis requant is fully specified and proven. **mesa's two bugs:** (1) it emits a *contiguous*
A/D/float layout, but the vendor (and the HW) want the **interleaved `[8×i32 A | 8×i16 B | 8×i16 C]`** per
8-oc group; (2) it never writes **C** at all. Fix = interleaved layout + the validated C.

**Blocker for C:** it needs per-channel `wt_sc[oc]`, but the teflon `pipe_ml` API exposes only ONE
per-tensor `weight_tensor->scale` (rkt_coefs.c:410), and per-axis int8 weights are each normalised to
±127 so the relative scale **cannot be recovered from the weights** — the per-channel scales must be
plumbed from the tflite (per-axis quant params) through the teflon delegate into `pipe_tensor`. That
plumbing + the interleaved-[A|B|C]-with-C emit is the implementation. The **float surface** (0x5024)
role is still open (it is NOT the weights); next board test = does interleaved ABC-with-correct-C
compute with a zeroed float surface, i.e. is the surface even load-bearing for per-axis.

## 2026-06-25 (evening) — per-axis delegates + runs on HW (gate fixed), but the live MAC still doesn't turn over

Pushed the validated per-axis ABC encoder all the way onto the hardware, clearing gates in sequence:
- **The float surface is per-channel DERIVABLE fields, not an opaque blob** (round-2 position-encoded
  captures, `g_bias`/`g_const`/`g_pt`, 5-way cross-model isolation): a **bias field = −bias[oc]** in
  float (`g_bias` shows −300,−400,… = −(oc+1)·100), a per-channel **scale** field, and global constant
  blocks (a 1344-long `in_sc`=0.0078 block, two 64-blocks). The bias formula is decoded; the **tiling is
  intricate/fragmented** (channel-offset, ~3 runs of ~128) and the weight-value placement looks
  data-dependent — the genuinely hard remaining piece. **`g_pt` (per-tensor) is structurally different**
  (ABC region 512B = A-only, no interleaved B/C; float surface = 861 distinct continuous values = the
  toolkit blob), so the per-axis decode does NOT transfer to a per-tensor MobileNet.
- **MobileNetV1 is PER-TENSOR uint8** (every conv: n_scales=1), not per-axis — correcting a premise that
  ran through this whole journal. So a per-axis encoder needs a per-axis model (re-quantise MobileNet, or
  ship per-axis layers).
- **Built a real per-axis int8 tflite with TensorFlow** (`vendor-capture/build_perax_tflite.py`,
  installed TF on the host) — 1×1 pointwise 16→128, weight nscales=128, non-saturating output
  (distinct=206), verified on the host.
- **The rocket driver explicitly REJECTED per-axis** at the support gate (`rkt_ml.c:427`
  `tensor_quantization_supported` returned false when `scales != NULL`), so teflon never delegated it —
  the first board run was a silent CPU fallback (maxdiff=0 but no submit). **Relaxed the gate** to allow
  per-axis weights/bias (the encoder handles them); now teflon **delegates + submits a real NPU job**
  (`rocket dbg submit`, weights BO loaded, `buf wt distinct=247`).
- **And the board's verdict: the conv still does not compute.** NPU output `distinct=1` (constant),
  `maxdiff=127`, `core wt_rd=0`, `ds0=h=0,w=0`. **Identical wall to per-tensor `conv2d-cal`.** So the
  live-mesa MAC failing to turn over is **independent of the coefficient buffer and of per-tensor/
  per-axis** — the validated ABC is necessary but not sufficient. Only the **vendor's exact full buffer
  (replay milestone) computes**; mesa's own ABC + a non-exact float surface (zeroed or dense) does not.

**Net:** tonight cleared the per-axis path end-to-end (encoder validated, gate opened, delegation +
submit working) and the hardware then localised the real live blocker one layer deeper: the conv's MAC
produces a constant — the **CBUF→CMAC / geometry (`ds0=h0,w0`) wall** the vendor regcmd clears and mesa's
doesn't, OR the requirement for the **exact** (blob-tiled) float surface. The coefficient-buffer work
(byte-exact ABC, half-decoded float fields) is correct but sits downstream of this. NEXT: chase why the
live mesa regcmd leaves `ds0=h0,w0` (geometry not latching) vs the vendor's, OR finish the float-surface
tiling — the two candidate live blockers. Patches: `mesa-patches/0002` (encoder) + the gate relax.

## 2026-06-25 (late evening) — the wall is the buffer (not the regcmd); the float surface = derivable skeleton + a data-dependent weight scatter

Two decisive isolations, both judged by the VALID oracle (output maxdiff/distinct on a non-saturating
model — NOT `core wt_rd`, which is a red herring that bit again):

- **regcmd vs buffer.** Fed the EXACT vendor coef buffer (`vendor-bias.bin`) to LIVE mesa (mesa's own
  regcmd) on the non-saturating `conv2d-cal`: NPU output **distinct=256, a rich feature map**. So the
  MAC turns over on the live path with the right buffer ⇒ **mesa's regcmd is FINE; the coefficient
  buffer is the wall.** (maxdiff was large only because vendor-bias is conv2d's ABC fed to cal — the
  ABC out_sc mismatch; the point is the MAC *computed*.) This re-explains every prior "degenerate live
  conv": it was the buffer (float surface), not geometry.
- **float surface = weights?** Per-axis end-to-end test (perax_pw, the TF-built per-axis tflite, now
  delegating): validated ABC + a **dequant-weight** float surface → **distinct=1, degenerate**. So the
  float surface is **NOT** the dequantised weights — clean negative from the valid oracle (kills the
  "second copy of the weights" hypothesis the whole journal carried).

**The float surface dissected (from the 5 position-encoded captures) — it is NOT a fragmented blob:**
contiguous per-channel arrays. ~90% of the nonzero structure is fixed across models (differences are
value-dependent zeros, not placement). The arrays:
- `@2676` len 124: **BIAS array = −bias[oc]**, contiguous, slot = base+oc (g_bias shows −(oc+1)·100).
  **Derivable.**
- `@1216` len 1456: the `in_sc` (=0.0078) constant block. **Derivable.**
- a per-channel **scale** field. **Derivable.**
- `@386`/`@4724`/`@3600`: **weight-VALUE arrays placed data-dependently** — g_const's weight 64 lands at
  `@386`, pw_ic's top weights 14/15/16 land at `@4724`: each model drops its weight values into
  value-sorted/sparse bins. **This is the genuine non-derivable blob — and it is ONLY the weight
  placement, not the whole surface.**

So the wall is precisely localised: the float surface is a **derivable skeleton** (bias = −bias[oc],
in_sc, scale) **+ a data-dependent weight scatter**. NEXT decisive test (answers per-axis derivability):
fill ONLY the skeleton (bias+in_sc+scale), leave the weight arrays zeroed, end-to-end on perax_pw — if
it computes, the weight scatter is NOT load-bearing and per-axis is fully derivable; if it degenerates,
the weight scatter is the (data-dependent) wall. Lesson re-logged: do NOT trust `core wt_rd`; only the
output on a non-saturating, carrier-matched model is the oracle.

## 2026-06-25 (night, close-out) — the per-axis carrier itself doesn't compute richly; the day's wins stand, the validation is blocked on a fresh question

Spent the evening tuning the float surface on `perax_pw` (the TF per-axis tflite) and it degenerated
every time — zeroed, dense dequant-weights, derivable-skeleton, AND a *valid same-shape* buffer
(`pw_oc`'s captured coef): output distinct 1–4 in every case. Contrast: `conv2d-cal` + a *wrong-out_sc*
vendor buffer stays **distinct=256** (rich). So either `perax_pw` is a broken carrier (int8 activations
/ 1x1 / 8x8 path) OR it was simply never handed a *correct* buffer (its own vendor coef, which the
tflite↔rknn arm64 mismatch blocks me from capturing). **Unresolved — and it confounded every per-axis
end-to-end test tonight.** One thing ruled out cheaply: the OUT_CVT offset (`rkt_regcmd.c:345`,
`out_offset = output_zero_point - 0x80`) *does* handle int8 (zp=0 → −128), so int8 output is not an
obvious break.

**Solid, banked results of the day (these don't come undone):**
1. per-axis **ABC encoder byte-exact validated** (pw_oc/pw_ic 1024/1024); support gate opened so teflon
   delegates per-axis.
2. **The wall is the buffer, not the regcmd** — vendor buffer on live mesa → distinct=256 (judged by the
   *valid* oracle, output on a non-saturating model, after relapsing to the `wt_rd` red herring and being
   caught).
3. **Float surface = derivable skeleton + data-dependent weight scatter**, precisely localised: bias
   array = −bias[oc] (@2676 contiguous), in_sc block (@1216), per-channel scale — derivable; the
   weight-VALUE arrays (@386/@4724/@3600) are value-sorted/sparse — the genuine blob, and only that part.
4. The `bufsize` floor fix (small convs under-allocated the float region → OOB).
5. Host toolchain: TF builds+verifies per-axis int8 tflites; capture-decode + byte-validate scripts.

**Two fresh-mind restart paths (both high-risk/precision — do NOT do tired):**
(a) Diagnose why `perax_pw` won't compute richly — is it a broken int8/pointwise carrier, or never given a
correct buffer? (Cleanest probe: get `perax_pw`'s own vendor coef — needs the ONNX→rknn route around the
arm64 tflite-load block + the TF/rknn protobuf conflict, i.e. a separate venv.)
(b) Validate the float-surface skeleton on `conv2d-cal` (the carrier that DOES compute) — needs the
per-TENSOR skeleton decode, with the caveat that per-tensor per-channel scale may be toolkit-invented
(the blob) and not derivable. Both are precision work; tonight was 13 flashes.
