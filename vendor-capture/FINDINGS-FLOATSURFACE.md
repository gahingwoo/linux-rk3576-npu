# The SDP coefficient float surface is NOT an opaque blob (2026-06-25)

Working the per-tensor conv2d (16->128, 5x5) coefficient buffer by trial-and-error
on the captures + the maxdiff oracle. The headline reversal: the float surface that
test (b) proved is **load-bearing** is **not** a data-dependent opaque blob — it is a
mostly-derivable per-channel skeleton plus a weight-valued region with visible
OIHW-ordered structure. The earlier "per-tensor = blob, not derivable" call was wrong.

## What test (b) showed
`conv2d-cal` (out_sc 1/32, out_zp 128, non-saturating) fed the full vendor coef buffer
-> output `distinct=256` (rich, correct geometry). Zero the non-skeleton float-surface
slots (keep ABC + the in_sc/structural skeleton) -> output `distinct=2`, pinned to
out_zp = degenerate. So for per-tensor the weight-valued region is load-bearing; the
skeleton alone is not enough.

## What the float surface actually contains (conv2d's own coef, `vendor-bias.bin`)
4944 f32, 2707 nonzero, but only **246 distinct values** (not the ~2477 a true
data-dependent blob would carry):
- `0.0078` (= in_sc) x1472, contiguous block @1216 -> the in_sc skeleton (derivable)
- `-2.25` / `1.998` x32 each, stride-13 structural blocks (fixed constants, derivable)
- a region where **~60-65% of the distinct values are wt_sc x integer** (wt_sc=3.9125),
  the integers being individual dequantised weight values `wq - wt_zp`
- at least 4 windows decode as conv2d's weights in **OIHW (oc,ic,ky,kx) order**:
  - fs@4   len124 -> OIHW idx 30990 (oc77,ic7,ky3,kx0)  -- 124-long contiguous match
  - fs@4736 len156 -> OIHW idx 16766
  - fs@4696 len 39 -> OIHW idx 16726
  - fs@4912 len 28 -> OIHW idx 16330
  A 124-long contiguous signed-integer match is not coincidence: the surface holds
  real dequant weights, in OIHW-local order, tiled into windows.

So the value content is derivable; the open question is the **window placement**
(which OIHW windows land at which float-surface offsets).

## Why the placement did not crack offline
The position-encoded captures we already have (idg_A/B/C = w encodes ky*5+kx / ic / oc;
pw_oc/pw_ic) do **not** cleanly decode the coef float surface:
- their coef-surface values are per-channel **scaled** (bias-like terms run to ~10960,
  far beyond the 1..25 / 1..16 / 1..128 encoding), so the position code is buried under
  the per-channel bias/scale
- the co-located all-nonzero slots are dominated by the stride-13 skeleton block, which
  decodes to a single constant coordinate (garbage for a placement map)
- the existing captures are all **different conv shapes** (coef lengths 4944 vs 5192 vs
  5224), so their nonzero-slot masks cannot be compared to conv2d's to test
  position-fixed vs value-dependent placement

This is a genuinely entangled multi-field buffer; reading one ambiguous capture in more
ways only reframes, it does not decide. The decisive test needs a *matched* probe.

## The staged decisive experiment: posprobe_a / posprobe_b
`build_posprobe.py` builds two rknns of conv2d's **exact** shape (per-tensor, 16->128,
5x5):
- `posprobe_a` weights = position RAMP `((lin*37)%251 - 125)/64` (lin = OIHW index)
- `posprobe_b` weights = different random set
Capture both, then:
1. compare their nonzero-slot **masks**. Jaccard -> 1.0 (same slots, different values)
   = placement is position-fixed = derivable. < 1 = value-dependent = blob.
2. if position-fixed: the `*37 mod 251` ramp makes consecutive OIHW weights distinct, so
   each window's values decode its start lin and length -> the full placement map -> the
   `rkt_coefs.c` float-surface encoder can be written to reproduce known bytes.

Matched shape + own-built (no toolkit-version confound) makes this the clean decider the
existing captures cannot be.

## Status of the derivability ledger
- regcmd / geometry: fine (vendor buffer -> distinct=256)
- ABC requant header: derivable, byte-validated (pw_oc/pw_ic)
- float-surface skeleton (in_sc, structural blocks, bias array): derivable
- float-surface weight-valued region: values derivable (dequant weights, OIHW-local
  order); **window placement = the one open question**, posprobe is staged to decide it

## UPDATE 2026-06-25 night — posprobe captured: NUANCED (not blob, not clean-derivable)
Flashed posprobe_a (*37 ramp) + posprobe_b (first gaussian, then corrected to *53 ramp).
Decode of the coef float surface:
- weight slots are LARGELY co-located between a and b, and BOTH lay out clean OIHW-consecutive
  ramps (a steps +37, b steps +53 per slot, exactly the ramp multipliers) -> the slots and the
  local OIHW-consecutive ORDER are position-fixed = derivable at that level.
- BUT at a fixed slot the OIHW *content* differs by a piecewise-constant offset: fs@9 window
  a holds OIHW lin0=79, b holds 83 (+4); other regions differ by +12 and +123. So which OIHW
  range maps to which window carries a **model(weight)-dependent phase**.
- The phase is NOT zero-skip compression (a has 1 zero before lin79, b has 0 before lin83 —
  off by 1, not 4). Origin unknown.
Verdict: a THIRD case — neither opaque value-dependent blob (it is highly structured: 93% of
contiguous weight transitions are OIHW +1 or exact-repeat) nor purely shape-derivable (the
per-region OIHW phase shifts with the weights). Pure mesa derivation is blocked on this phase law.
Next (chosen): flash more ramps (*43,*61) to see how the per-window phase varies with the
multiplier and try to fit the phase law. (lin_a==lin_b self-test separated the hypotheses cleanly
at 100% vs 1%, so the 0% here is real, not a decoder artifact; the offset is piecewise-constant.)

## UPDATE 2026-06-25 late — 4-multiplier test SETTLES it: VALUE-DEPENDENT placement
Flashed posprobe_a/b/c/d = *37/*53/*43/*61 ramps (d degenerate: toolkit gave it a 2x
per-tensor scale, halving the resolution, so its OIHW ramp wasn't preserved — dropped).
On the 3 clean models (same shape, same scale 0.01562, same uniform no-zero distribution),
comparing the OIHW position decoded at each genuine ramp slot:
- at the SAME fs slot 9: a holds OIHW 79, b holds 83, c holds 119 — different content.
- OIHW position 79 sits at fs slot 9 in a, fs slot 447 in b, fs slot 220 in c — different
  physical slots entirely.
- the window STRUCTURE differs per model: a = one 247-run @fs9; b = 124-run @fs8 + 123-run
  @fs133; c = 25-run @fs8 + 222-run @fs34. Lengths, break points, fs offsets all differ.
- no simple law fits the per-window start across multipliers (ruled out constant, C*inv(m),
  C*m, linear-in-m offline).
VERDICT: the float-surface weight PLACEMENT is value-dependent — the layout (which OIHW range,
at which fs offset, in what run lengths) depends on the specific weight values. The LOCAL
structure (OIHW-consecutive runs) is real and derivable, but the placement of those runs is the
toolkit compiler's value-driven heuristic. For a from-scratch mesa encoder that must reproduce
the vendor bytes, this is effectively a blob. (Earlier "structured tiling, likely derivable"
reframe: half right — local order derivable, run placement is not.)

## The open, untested, HOPEFUL question
The vendor's value-dependent placement may be an OPTIMIZATION (compression / ordering for speed),
not a CORRECTNESS requirement. The hardware may accept any valid layout — e.g. a canonical plain
OIHW float surface, which IS fully derivable. This is testable WITHOUT vendor capture: write a
canonical-OIHW float-surface encoder in rkt_coefs.c and judge with the test_conv.py maxdiff oracle
(mainline kernel path). If a canonical layout computes correctly -> the vendor's value-dependence
was never needed -> placement is derivable after all and the wall is broken. Next direction.

## UPDATE 2026-06-26 — pivot REFUTED: placement is load-bearing, not just optimization
Ran two candidates off vendor-bias.bin (which computes, distinct=256), touching ONLY the
weight-scatter slots (skeleton/ABC byte-identical), judged by test_conv.py maxdiff:
- H-shufW (weight slots shuffled among themselves, same multiset) -> NPU distinct=1 / all-128
  zero-rail / maxdiff=128 (clean first submit). Right values, wrong order -> degenerate.
- plain-OIHW (weight slots refilled in plain OIHW order) -> also maxdiff=128.
So the value-to-slot placement is LOAD-BEARING: deriving the mask and filling any/plain order
does NOT compute. Combined with the posprobe result (placement is value-dependent, no law),
the float surface is a genuine blob for a from-scratch derivable encoder. The hopeful pivot
(vendor layout = optimization the hw tolerates) is refuted.
Residual cheap untested candidate: value-SORTED fill (posprobe showed local order is OIHW not
value-sorted, so low odds). Realistic paths now: extract/replay per-conv (allbilly's suggestion,
not upstreamable) or a deep RE of the placement algorithm.
