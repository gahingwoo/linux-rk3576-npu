#!/bin/sh
# ---------------------------------------------------------------------------
# Diff rocket's dumped conv0 regcmd (from a dmesg log) against the vendor's
# captured conv0 regcmd.  Both use "tgt=.. reg=.. val=.." lines, so the same
# parser reads both.  The 5 DMA address registers are IOVAs that legitimately
# differ run-to-run, so they're noted but never flagged.
#
# Usage: conv0-diff.sh <rocket-dmesg-log> <vendor-conv0.txt>
# ---------------------------------------------------------------------------
ROCK="${1:-/tmp/npu-dmesg.log}"
VEND="${2:-/opt/npu-test/vendor-conv0.txt}"

# Pull out the conv0 regcmd dump block.  conv0 is the FIRST regcmd dump (job 1)
# and is the only one whose CNA FC_CON1 (reg=1064) = 0x777 (firstconv mode), so
# prefer the block containing that; fall back to the first block.  Using the
# LAST block grabs layer 2 (normal path) and produces bogus diffs.
ROCK_BLOCK=/tmp/rocket-conv0-block.txt
awk '
  /regcmd dump: count=/ { nblk++; blk[nblk]="" }
  /tgt=[0-9a-f]+ reg=[0-9a-f]+ val=[0-9a-f]+/ { if(nblk>0) blk[nblk]=blk[nblk] $0 "\n" }
  END {
    pick=1
    for(i=1;i<=nblk;i++) if(blk[i] ~ /reg=1064 val=0*777/) { pick=i; break }
    printf "%s", blk[pick]
  }' "$ROCK" > "$ROCK_BLOCK" 2>/dev/null
[ -s "$ROCK_BLOCK" ] || grep -E "tgt=[0-9a-f]+ reg=[0-9a-f]+ val=[0-9a-f]+" "$ROCK" > "$ROCK_BLOCK" 2>/dev/null

awk '
function parse(line,   i,n,f,t,r,v) {
  n=split(line,f," "); t="";r="";v=""
  for(i=1;i<=n;i++){
    if(substr(f[i],1,4)=="tgt=")t=substr(f[i],5)
    else if(substr(f[i],1,4)=="reg=")r=substr(f[i],5)
    else if(substr(f[i],1,4)=="val=")v=substr(f[i],5)
  }
  if(t!=""&&r!=""&&v!=""){KEY=t":"r;VAL=v;return 1}
  return 0
}
BEGIN{
  # address regs (IOVAs differ run-to-run): feature, weights, output, bias x2
  ig["0201:1088"]=1; ig["0201:1110"]=1; ig["1001:4018"]=1
  ig["2001:5020"]=1; ig["2001:5024"]=1
}
FNR==NR{ if(parse($0)){vend[KEY]=VAL; if(!(KEY in vseen)){vseen[KEY]=1; vo[++vn]=KEY}} next }
{ if(parse($0)){rock[KEY]=VAL; if(!(KEY in rseen)){rseen[KEY]=1; ro[++rn]=KEY}} }
END{
  print "----- conv0 regcmd diff: rocket vs vendor (addr regs ignored) -----"
  if(rn==0){ print "  !!! NO rocket regcmd found in dmesg — dump did not fire !!!"; exit }
  d=0
  for(i=1;i<=vn;i++){k=vo[i]
    if(k in ig) continue
    if(!(k in rock)){ printf "  MISSING in rocket: %s (vendor=%s)\n",k,vend[k]; d++ }
    else if(rock[k]!=vend[k]){ printf "  DIFF %s: rocket=%s  vendor=%s\n",k,rock[k],vend[k]; d++ }
  }
  for(i=1;i<=rn;i++){k=ro[i]
    if(k in ig) continue
    if(!(k in vend)){ printf "  EXTRA in rocket: %s=%s\n",k,rock[k]; d++ }
  }
  print  "  --- address regs (informational, not flagged) ---"
  for(i=1;i<=vn;i++){k=vo[i]; if(k in ig) printf "    %s: rocket=%s vendor=%s\n",k,(k in rock)?rock[k]:"MISSING",vend[k]}
  if(d==0) print "  *** IDENTICAL (ignoring addresses) -> regcmd is NOT the conv0 bug ***"
  else     printf "  >>> %d divergence(s) -> conv0 bug candidate(s) <<<\n",d
  printf "  (rocket non-addr entries=%d, vendor entries=%d)\n",rn,vn
}
' "$VEND" "$ROCK_BLOCK"
