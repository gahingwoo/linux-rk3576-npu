#!/bin/sh
# ---------------------------------------------------------------------------
# RK3576 NPU rocket-driver output diagnostic.
#
# Automates the manual "grep the kernel log after an inference" workflow:
# reads the rocket driver's debug lines (perf bandwidth counters, regcmd
# dumps, DPU state, prep_bo readback) plus the Teflon inference result, and
# prints a single root-cause verdict for the all-zero-output problem.
#
# Usage:
#   npu-diag.sh [dmesg_file] [infer_output_file]
# With no args it reads live `dmesg` and /tmp/npu-infer.log (if present).
#
# Key signal: the vendor DMA bandwidth counters printed as
#   "rocket dbg perf: dt_wr=N dt_rd=N wt_rd=N"
#   dt_wr = bytes the DPU wrote to DRAM   (output write-back)
#   dt_rd = feature/input data read
#   wt_rd = convolution weights read
# These are hardware counters, independent of CPU cache, so they decide
# whether a zero result is "NPU never computed/wrote" vs "cache/address bug".
# ---------------------------------------------------------------------------

DMESG_SRC="${1:-}"
INFER_SRC="${2:-/tmp/npu-infer.log}"

TMPD="$(mktemp -d /tmp/npu-diag.XXXXXX)"
trap 'rm -rf "$TMPD"' EXIT
DMESG="$TMPD/dmesg.txt"
INFER="$TMPD/infer.txt"

if [ -n "$DMESG_SRC" ] && [ -f "$DMESG_SRC" ]; then
	cp "$DMESG_SRC" "$DMESG"
else
	dmesg > "$DMESG" 2>/dev/null
fi
if [ -f "$INFER_SRC" ]; then
	cp "$INFER_SRC" "$INFER"
else
	: > "$INFER"
fi

bar() { printf '%s\n' "============================================================"; }
say() { printf '%s\n' "$*"; }

bar
say "RK3576 NPU rocket-driver output diagnostic"
say "  kernel : $(uname -r 2>/dev/null)"
say "  date   : $(date 2>/dev/null)"
bar

# ── 1. Did the driver run / any hard errors? ───────────────────────────────
PERF_N=$(grep -c "rocket dbg perf"   "$DMESG" 2>/dev/null || echo 0)
RCMD_N=$(grep -c "rocket dbg regcmd" "$DMESG" 2>/dev/null || echo 0)
ERR=$(grep -iE "rocket.*(timeout|fault)|rknn.*(iommu|fault)|DMA_(READ|WRITE)_ERROR|job timed out" "$DMESG" 2>/dev/null | head -5)

if [ "$PERF_N" -eq 0 ] && [ "$RCMD_N" -eq 0 ]; then
	say "VERDICT: NO ROCKET DEBUG OUTPUT FOUND."
	say "  The rocket driver produced no 'rocket dbg' lines in this dmesg."
	say "  Either no inference ran, the debug kernel isn't booted, or the"
	say "  dmesg ring buffer was overwritten. Re-run inference, then this tool."
	bar
	exit 2
fi

say "Jobs observed : perf=$PERF_N regcmd=$RCMD_N"

if [ -n "$ERR" ]; then
	say ""
	say "HARDWARE ERRORS detected in dmesg:"
	printf '  %s\n' "$ERR"
fi

# ── 2. regcmd geometry ─────────────────────────────────────────────────────
COUNT=$(grep "rocket dbg regcmd" "$DMESG" | sed -n 's/.*count=\([0-9]*\).*/\1/p' | tail -1)
[ -n "$COUNT" ] && say "regcmd count  : $COUNT (entries per job)"

# ── 3. Bandwidth counters (the decisive signal) ────────────────────────────
# Counters are cumulative on RK3576 (per-job clear does not reset them); take
# the max (= session total).  New format prints TOP and CORE blocks separately:
#   rocket dbg perf: top[dt_wr=A dt_rd=B wt_rd=C] core[dt_wr=D dt_rd=E wt_rd=F]
# CORE = CNA/CMAC/DPU tensor traffic (the meaningful one for compute);
# TOP   = PC/IOMMU front-end (dominated by command-descriptor fetches).
PERF=$(grep "rocket dbg perf" "$DMESG" | \
	sed -n 's/.*top\[dt_wr=\([0-9]*\) dt_rd=\([0-9]*\) wt_rd=\([0-9]*\)\] core\[dt_wr=\([0-9]*\) dt_rd=\([0-9]*\) wt_rd=\([0-9]*\)\].*/\1 \2 \3 \4 \5 \6/p' | \
	awk 'BEGIN{n=6; for(i=1;i<=n;i++)m[i]=0}
	     {for(i=1;i<=n;i++) if($i>m[i])m[i]=$i}
	     END{if(NR>0) printf "%d %d %d %d %d %d", m[1],m[2],m[3],m[4],m[5],m[6]}')

if [ -z "$PERF" ]; then
	# Fall back to the old single-block format.
	PERF=$(grep "rocket dbg perf" "$DMESG" | \
		sed -n 's/.*dt_wr=\([0-9]*\) dt_rd=\([0-9]*\) wt_rd=\([0-9]*\).*/0 0 0 \1 \2 \3/p' | \
		awk 'BEGIN{n=6; for(i=1;i<=n;i++)m[i]=0}
		     {for(i=1;i<=n;i++) if($i>m[i])m[i]=$i}
		     END{if(NR>0) printf "%d %d %d %d %d %d", m[1],m[2],m[3],m[4],m[5],m[6]}')
fi

TOP_WR=$(echo "$PERF" | cut -d' ' -f1); TOP_RD=$(echo "$PERF" | cut -d' ' -f2); TOP_WT=$(echo "$PERF" | cut -d' ' -f3)
DT_WR=$(echo "$PERF"  | cut -d' ' -f4); DT_RD=$(echo "$PERF"  | cut -d' ' -f5); WT_RD=$(echo "$PERF"  | cut -d' ' -f6)
TOP_WR=${TOP_WR:-0}; TOP_RD=${TOP_RD:-0}; TOP_WT=${TOP_WT:-0}
DT_WR=${DT_WR:-0};  DT_RD=${DT_RD:-0};   WT_RD=${WT_RD:-0}

# Per-job variance of CORE dt_rd. Counters are cumulative, so the per-job read
# is the delta between consecutive lines. If every positive delta is identical,
# dt_rd is a FIXED per-job overhead (command/descriptor fetch), NOT real
# feature-map traffic — different conv layers differ in size by 100x, so real
# feature reads must vary. Distinct-positive-delta count tells the two apart.
DRD_DISTINCT=$(grep "rocket dbg perf" "$DMESG" | \
	sed -n 's/.*core\[dt_wr=[0-9]* dt_rd=\([0-9]*\).*/\1/p' | \
	awk 'NR>1{d=$1-prev; if(d>0)seen[d]=1} {prev=$1} END{n=0; for(k in seen)n++; print n+0}')
DRD_DISTINCT=${DRD_DISTINCT:-0}

say ""
say "DMA bandwidth (cumulative, hardware counters):"
say "  CORE (CNA/CMAC/DPU)  : dt_wr=$DT_WR  dt_rd=$DT_RD  wt_rd=$WT_RD"
say "  TOP  (PC/IOMMU)      : dt_wr=$TOP_WR  dt_rd=$TOP_RD  wt_rd=$TOP_WT"
say "  CORE dt_rd per-job   : $DRD_DISTINCT distinct delta(s)  ($([ "$DRD_DISTINCT" -le 1 ] 2>/dev/null && echo 'constant = command overhead, NOT feature traffic' || echo 'varies = real per-layer feature reads'))"

# EXECUTER engage, sampled DURING execution (reliable, unlike a post-done read).
# "rocket dbg exec: ever_bit16 CNA=N CORE=N DPU=N RDMA=N (samples=N)". OR across
# all jobs: if a unit ever shows 1, its executer DID run at least once.
EXEC=$(grep "rocket dbg exec" "$DMESG" | \
	sed -n 's/.*CNA=\([01]\) CORE=\([01]\) DPU=\([01]\) RDMA=\([01]\).*/\1 \2 \3 \4/p' | \
	awk 'BEGIN{c=0;o=0;d=0;r=0}
	     {if($1)c=1; if($2)o=1; if($3)d=1; if($4)r=1}
	     END{if(NR>0) printf "%d %d %d %d", c,o,d,r}')
if [ -n "$EXEC" ]; then
	EX_CNA=$(echo "$EXEC" | cut -d' ' -f1); EX_CORE=$(echo "$EXEC" | cut -d' ' -f2)
	EX_DPU=$(echo "$EXEC" | cut -d' ' -f3); EX_RDMA=$(echo "$EXEC" | cut -d' ' -f4)
	yn() { [ "$1" = 1 ] && echo "ENGAGED" || echo "never"; }
	say ""
	say "EXECUTER engage (bit16, sampled during run — reliable):"
	say "  CNA=$(yn "$EX_CNA")  CORE=$(yn "$EX_CORE")  DPU=$(yn "$EX_DPU")  RDMA=$(yn "$EX_RDMA")"
fi

# ── 4. Inference result ────────────────────────────────────────────────────
NONZERO=$(grep "Raw non-zero" "$INFER" | sed -n 's/.*Raw non-zero:[[:space:]]*\([0-9]*\).*/\1/p' | tail -1)
NPU_TOP1=$(grep "Top-1 index"  "$INFER" | sed -n 's/.*Top-1 index:[[:space:]]*\([0-9]*\).*/\1/p' | tail -1)
CPU_TOP1=$(grep "CPU Top-1"    "$INFER" | sed -n 's/.*CPU Top-1:[[:space:]]*\([0-9]*\).*/\1/p' | tail -1)
NONZERO=${NONZERO:-unknown}

say ""
say "Inference result:"
say "  NPU output non-zero : $NONZERO"
[ -n "$NPU_TOP1" ] && say "  NPU Top-1           : $NPU_TOP1"
[ -n "$CPU_TOP1" ] && say "  CPU Top-1 (ref)     : $CPU_TOP1"

# ── 5. prep_bo cache readback summary ──────────────────────────────────────
PB=$(grep "rocket dbg prep_bo" "$DMESG" | tail -3)
if [ -n "$PB" ]; then
	say ""
	say "Last output-buffer prep_bo readback:"
	printf '  %s\n' "$(echo "$PB" | sed 's/.*prep_bo: //')"
fi

# ── 5b. HYPOTHESIS BOARD ───────────────────────────────────────────────────
# Settle every suspicion we've raised about why the RK3576 NPU outputs zeros,
# from the live kernel dmesg evidence. Each line: STATUS + evidence.
#   RULED OUT = evidence shows this is fine / not the cause
#   SUSPECT   = evidence is consistent with this being (part of) the cause
#   GATE      = strongest current root-cause candidate
#   n/a       = needed evidence not present in this log

# regval REG  -> first-job value (hex string) of a regcmd entry "reg=REG val=.."
regval() { grep -m1 "reg=$1 val=" "$DMESG" 2>/dev/null | sed -n 's/.*val=\([0-9a-f]*\).*/\1/p'; }
hex2d()  { [ -n "$1" ] && printf '%d' "$((0x$1))" 2>/dev/null || echo ""; }

say ""
bar
say "HYPOTHESIS BOARD — every suspected cause vs the live evidence"
bar

# H1 — executer engage (the current prime gate)
if [ -n "$EXEC" ]; then
	if [ "$EX_CNA" = 0 ] && [ "$EX_CORE" = 0 ] && [ "$EX_DPU" = 0 ]; then
		say "H1 ARMING/ENGAGE [GATE]   : CNA/CORE/DPU bit16 NEVER set in $( grep -c 'rocket dbg exec' "$DMESG") jobs"
		say "     (RDMA=$(yn "$EX_RDMA")). CBUF-backed compute executers never run."
	else
		say "H1 ARMING/ENGAGE [RULED OUT]: some compute unit DID engage"
		say "     CNA=$(yn "$EX_CNA") CORE=$(yn "$EX_CORE") DPU=$(yn "$EX_DPU") RDMA=$(yn "$EX_RDMA")"
	fi
else
	say "H1 ARMING/ENGAGE [n/a]    : no 'rocket dbg exec' lines (old kernel?)"
fi

# H2 — real tensor DMA vs command overhead
if [ "$DT_RD" -gt 0 ] 2>/dev/null; then
	if [ "$DRD_DISTINCT" -le 1 ] 2>/dev/null; then
		say "H2 TENSOR DMA   [GATE]    : core dt_rd constant/job ($DRD_DISTINCT delta) = cmd overhead,"
		say "     not feature traffic — CNA never streams the feature map."
	else
		say "H2 TENSOR DMA   [RULED OUT]: core dt_rd varies per layer ($DRD_DISTINCT deltas) = real reads"
	fi
else
	say "H2 TENSOR DMA   [GATE]    : core dt_rd=0 — no feature reads at all"
fi

# H3 — weight fetch
DCOMP=$(regval 1110); WSZ0=$(regval 1030)
if [ "$WT_RD" -gt 0 ] 2>/dev/null; then
	say "H3 WEIGHT FETCH [RULED OUT]: wt_rd=$WT_RD (weights are read)"
else
	say "H3 WEIGHT FETCH [SUSPECT] : wt_rd=0. regcmd DCOMP_ADDR0=0x${DCOMP:-?} WEIGHT_SIZE0=0x${WSZ0:-?}"
	say "     (addr/size look set, so the value isn't missing — weights just never DMA'd;"
	say "     likely downstream of H1: no engage => no weight load)."
fi

# H4 — output write-back
if [ "$DT_WR" -gt 0 ] 2>/dev/null; then
	say "H4 OUTPUT WRITE [RULED OUT]: dt_wr=$DT_WR (DPU writes to DRAM)"
else
	say "H4 OUTPUT WRITE [GATE]    : dt_wr=0 every job — DPU never writes output (explains all-zero)"
fi

# H5 — cache coherency (cached vs DRAM). wc path is currently broken (NULL->deadbeef).
PB1=$(grep "rocket dbg prep_bo" "$DMESG" | tail -1)
if echo "$PB1" | grep -q "wc=deadbeef"; then
	say "H5 CACHE COHEREN[n/a]     : wc readback broken (memremap NULL->deadbeef); can't compare"
	say "     cached vs DRAM. But H4 dt_wr=0 means there's nothing in DRAM to be stale anyway."
elif echo "$PB1" | grep -qE "cached=00000000.* wc=[0-9a-f]"; then
	say "H5 CACHE COHEREN[SUSPECT] : cached=0 but wc!=0 — NPU wrote, CPU sees stale zeros"
else
	say "H5 CACHE COHEREN[info]    : $(echo "$PB1" | sed 's/.*prep_bo: //')"
fi

# H6 — ping-pong POINTER (bit0) alternation
PSTUCK=$(grep "rocket dbg submit" "$DMESG" | sed -n 's/.*CNA_SPTR=0x\([0-9a-f]*\).*/\1/p' | \
	awk '{b=("0x"$1)+0; p=b%2; if(p)one++; else zero++} END{printf "%d %d", zero+0, one+0}')
PZ=$(echo "$PSTUCK" | cut -d' ' -f1); PO=$(echo "$PSTUCK" | cut -d' ' -f2)
PZ=${PZ:-0}; PO=${PO:-0}; PTOT=$(( PZ + PO ))
# Healthy ping-pong toggles POINTER each job => ~50/50. Heavily lopsided = stuck.
PMIN=$PZ; [ "$PO" -lt "$PZ" ] && PMIN=$PO
if [ "$PTOT" -gt 0 ] && [ $(( PMIN * 4 )) -ge "$PTOT" ]; then
	say "H6 PINGPONG PTR [RULED OUT]: CNA POINTER alternates ~evenly (POINTER=0:$PZ POINTER=1:$PO)"
else
	say "H6 PINGPONG PTR [SUSPECT] : CNA POINTER STUCK (POINTER=0:$PZ POINTER=1:$PO) — not toggling"
	say "     each job's PP_CLEAR should flip it ~50/50; lopsided = ping-pong not advancing"
fi

# H7 — CBUF bank over-allocation (mesa assumes RK3588 12-bank CBUF)
CB0=$(regval 1040)
if [ -n "$CB0" ]; then
	CBV=$(hex2d "$CB0"); WB=$(( (CBV>>4) & 0xf )); DB=$(( CBV & 0xf ))
	TOT=$(( WB + DB ))
	say "H7 CBUF BANKS   [SUSPECT] : CBUF_CON0=0x$CB0 -> WEIGHT_BANK=$WB DATA_BANK=$DB total=$TOT"
	say "     (mesa caps at 12 = RK3588/NVDLA 384KB; if RK3576 CBUF is smaller, CNA can't stage)"
else
	say "H7 CBUF BANKS   [n/a]     : no full regcmd dump in log (CBUF_CON0 not found)"
fi

# H8 — op_en reaching the units
DPU_OPEN=$(grep "rocket dbg DPU:" "$DMESG" | sed -n 's/.*OP_EN=0x0*\([0-9a-f]*\).*/\1/p' | tail -1)
OPEN_BC=$(grep -m1 "reg=0008 val=0000007f" "$DMESG")
say "H8 OP_EN        [RULED OUT]: DPU OP_EN=0x${DPU_OPEN:-?}; broadcast 0x7f in regcmd=$([ -n "$OPEN_BC" ] && echo yes || echo NO)"

# H9 — CORE MAC gating
MG=$(regval 300c)
if [ "$MG" = "00000000" ]; then
	say "H9 MAC GATING   [RULED OUT]: CORE_MAC_GATING(0x300c)=0 (MAC un-gated)"
elif [ -n "$MG" ]; then
	say "H9 MAC GATING   [SUSPECT] : CORE_MAC_GATING(0x300c)=0x$MG (expected 0)"
else
	say "H9 MAC GATING   [n/a]     : 0x300c not in regcmd dump"
fi

# H10 — clocks
CLK_N=$(grep -c "rocket dbg clk" "$DMESG")
CLK_OFF=$(grep "rocket dbg clk" "$DMESG" | grep -c "hw_enabled=0")
if [ "$CLK_N" -gt 0 ]; then
	[ "$CLK_OFF" -eq 0 ] && say "H10 CLOCKS      [RULED OUT]: all NPU clocks hw_enabled=1" \
		|| say "H10 CLOCKS      [SUSPECT] : $CLK_OFF clock sample(s) hw_enabled=0"
else
	say "H10 CLOCKS      [n/a]     : no clk dump"
fi

# H11 — IOMMU / DMA / timeout errors
if [ -n "$ERR" ]; then
	say "H11 HW ERRORS   [SUSPECT] : $(echo "$ERR" | head -1)"
else
	say "H11 HW ERRORS   [RULED OUT]: no timeout / IOMMU fault / DMA error in dmesg"
fi

# H12 — conv config vs vendor (CONV_CON2 feature grains / kernel group)
CC2=$(regval 1010)
[ -n "$CC2" ] && say "H12 CONV CONFIG [info]    : CONV_CON2(0x1010)=0x$CC2 (cf vendor BSP; FEATURE_GRAINS/KERNEL_GROUP)" \
	|| say "H12 CONV CONFIG [n/a]     : 0x1010 not in dump"

# H13 — PC completion
PCRAW=$(grep "rocket dbg done" "$DMESG" | sed -n 's/.*PC_RAW=0x\([0-9a-f]*\).*/\1/p' | tail -1)
say "H13 PC DONE     [info]    : last PC_RAW=0x${PCRAW:-?} (0x3000000x = PC reached done)"

# ── 6. Verdict ─────────────────────────────────────────────────────────────
bar
if [ -n "$ERR" ]; then
	say "VERDICT: HARDWARE ERROR (timeout / IOMMU fault / DMA error)."
	say "  The job did not complete cleanly. Resolve the error above before"
	say "  interpreting output correctness."
	bar; exit 1
fi

if [ "$NONZERO" != "unknown" ] && [ "$NONZERO" -gt 0 ] 2>/dev/null; then
	if [ -n "$NPU_TOP1" ] && [ "$NPU_TOP1" = "$CPU_TOP1" ]; then
		say "VERDICT: PASS — NPU output is non-zero and Top-1 matches the CPU"
		say "  reference (index $NPU_TOP1). Inference is correct."
	else
		say "VERDICT: PARTIAL — NPU produced non-zero output but Top-1"
		say "  ($NPU_TOP1) != CPU ($CPU_TOP1). Compute runs; values are wrong."
		say "  Suspect quantization / scale / stride config, not the data path."
	fi
	bar; exit 0
fi

# Output is zero — use the bandwidth counters to localize.
if [ "$DT_WR" -gt 0 ] 2>/dev/null; then
	say "VERDICT: CACHE / ADDRESS BUG — DPU DID write to DRAM (dt_wr=$DT_WR)"
	say "  but userspace reads all-zero. The compute path works; the result"
	say "  is lost between DRAM and the CPU."
	say "  Suspect: dma_sync on the synthetic 'rknn' device not invalidating"
	say "  the CPU cache, or the output IOVA != the BO the CPU maps."
elif [ "$DT_RD" -gt 0 ] 2>/dev/null && [ "$DRD_DISTINCT" -le 1 ] 2>/dev/null; then
	say "VERDICT: ARMING / ENGAGE GATE — the NPU runs the command stream but the"
	say "  compute datapath never moves tensors. CORE dt_rd rises by a CONSTANT"
	say "  amount per job (= command/descriptor overhead, $DRD_DISTINCT distinct"
	say "  delta), while wt_rd=0 (no weights) and dt_wr=0 (no output) everywhere."
	say "  Real conv layers differ in size by 100x, so a layer-independent dt_rd"
	say "  means the CNA/CMAC/DPU executers accept the regcmd but never DMA"
	say "  feature data, weights, or output."
	say "  Suspect (upstream of compute, NOT a per-tensor value): S_POINTER/op_en"
	say "  arming, CBUF producer/consumer setup, PC task dependency, clocks,"
	say "  power domain, or reset ordering. Same class as the RK3568 sibling"
	say "  (executer 'bit16' never sets, dt_wr=0)."
elif [ "$WT_RD" -eq 0 ] 2>/dev/null && [ "$DT_RD" -gt 0 ] 2>/dev/null; then
	say "VERDICT: WEIGHT-FETCH GATE — CNA reads feature data (dt_rd=$DT_RD, which"
	say "  varies per layer = real traffic) but NEVER fetches weights (wt_rd=0)."
	say "  With no kernel weights the MAC produces zeros, so the DPU writes"
	say "  nothing (dt_wr=0) and the output is uniform zero-point."
	say "  Suspect the CNA weight-DMA setup: WEIGHT_DATA_ADDR / WEIGHT_SIZE,"
	say "  weight CBUF banking, or a weight-decompression enable."
elif [ "$WT_RD" -gt 0 ] 2>/dev/null && [ "$DT_WR" -eq 0 ] 2>/dev/null; then
	say "VERDICT: COMPUTE / WRITE-BACK GATE — input and weights are both read"
	say "  (dt_rd=$DT_RD wt_rd=$WT_RD) but the DPU never writes (dt_wr=0)."
	say "  CNA/CMAC load but the MAC->DPU write-back stage does not engage."
	say "  Suspect MAC enable (op_en bitmask), DPU WDMA enable, or the"
	say "  CORE->DPU dependency/handshake."
elif [ "$DT_RD" -eq 0 ] 2>/dev/null; then
	say "VERDICT: CORE NEVER MOVES TENSOR DATA — all CORE counters are 0"
	say "  (core dt_wr=0 dt_rd=0 wt_rd=0), while TOP shows dt_rd=$TOP_RD"
	say "  (PC command-descriptor fetches only)."
	say "  The CNA/CMAC/DPU executers consume the command list but never DMA"
	say "  feature data, weights, or output. This is an ARMING/ENGAGE gate"
	say "  upstream of compute: S_POINTER/op_en arming, CBUF setup, clocks,"
	say "  power domain, or reset ordering — NOT a per-tensor config value."
else
	say "VERDICT: ZERO OUTPUT, inconclusive counters"
	say "  (dt_wr=$DT_WR dt_rd=$DT_RD wt_rd=$WT_RD). Inspect dmesg manually."
fi
bar
exit 1
