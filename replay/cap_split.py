#!/usr/bin/env python3
"""
Split the vendor /proc/rknpu_cap blob into the payload files replay.c reads.

Input: either the raw blob pulled off the SD (/rknpu_cap.bin), or a serial log
containing the base64 between "BEGIN rknpu_cap.b64" / "END rknpu_cap.b64".

Blob format (little-endian):
    magic "RKC1"
    per section: [tag u32][iova u32][len u32][len bytes]
    tags: RGCD regcmd, INPT input, WGHT weights, BIAS bias.

Writes regcmd.bin / input.bin / weights.bin / bias.bin + meta.txt (regfg_amount,
the section IOVAs, and out_addr / bs1 offset scanned out of the regcmd) into the
output dir. The output BO isn't captured (it's the job's product) -- the host
computes a CPU reference from input+weights+bias for replay validation.

Usage: cap_split.py <rknpu_cap.bin | serial-log.txt> [outdir]
"""
import base64
import os
import re
import struct
import sys

MAGIC = b"RKC1"
TAGS = {b"RGCD": "regcmd", b"INPT": "input", b"WGHT": "weights", b"BIAS": "bias"}
FNAME = {"regcmd": "regcmd.bin", "input": "input.bin",
         "weights": "weights.bin", "bias": "bias.bin"}


def load_blob(path):
    data = open(path, "rb").read()
    if data[:4] == MAGIC:
        return data
    # treat as a serial/text log: pull the base64 block
    txt = data.decode("latin-1")
    m = re.search(r"BEGIN rknpu_cap\.b64\s*(.*?)\s*END rknpu_cap\.b64",
                  txt, re.S)
    if not m:
        sys.exit("no RKC1 magic and no 'BEGIN rknpu_cap.b64' block found")
    b64 = re.sub(r"[^A-Za-z0-9+/=]", "", m.group(1))
    blob = base64.b64decode(b64)
    if blob[:4] != MAGIC:
        sys.exit("decoded base64 does not start with RKC1 magic")
    return blob


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: cap_split.py <rknpu_cap.bin|serial-log.txt> [outdir]")
    outdir = sys.argv[2] if len(sys.argv) > 2 else "payload"
    os.makedirs(outdir, exist_ok=True)
    blob = load_blob(sys.argv[1])

    secs = {}
    off = 4
    while off + 12 <= len(blob):
        tag = blob[off:off + 4]
        iova, length = struct.unpack_from("<II", blob, off + 4)
        body = blob[off + 12:off + 12 + length]
        if len(body) != length:
            print(f"WARN: section {tag} truncated "
                  f"({len(body)}/{length}) -- transfer dropped bytes?")
        name = TAGS.get(tag)
        if name:
            secs[name] = (iova, body)
            open(os.path.join(outdir, FNAME[name]), "wb").write(body)
            print(f"  {name:8} iova=0x{iova:08x} {len(body)} bytes "
                  f"-> {FNAME[name]}")
        else:
            print(f"  <unknown tag {tag!r}> len={length}")
        off += 12 + length

    # meta: derive what replay needs from the regcmd + section iovas
    meta = {}
    if "regcmd" in secs:
        rc = secs["regcmd"][1]
        meta["regfg_amount"] = len(rc) // 8
        bs0 = bs1 = out = 0
        for i in range(len(rc) // 8):
            e = struct.unpack_from("<Q", rc, i * 8)[0]
            reg = e & 0xffff
            val = (e >> 16) & 0xffffffff
            if reg == 0x4018:
                out = val
            elif reg == 0x5020:
                bs0 = val
            elif reg == 0x5024:
                bs1 = val
        meta["out_addr"] = out
        meta["bs1_off"] = (bs1 - bs0) if bs1 > bs0 else 0x100
    for n in ("input", "weights", "bias"):
        if n in secs:
            meta[{"input": "in_addr", "weights": "wt_addr",
                  "bias": "bs_addr"}[n]] = secs[n][0]
    with open(os.path.join(outdir, "meta.txt"), "w") as f:
        for k, v in meta.items():
            f.write(f"{k}=0x{v:x}\n" if k.endswith("addr") or k == "bs1_off"
                    else f"{k}={v}\n")
    print("  meta.txt:", " ".join(f"{k}={v:#x}" if isinstance(v, int) and v > 255
                                   else f"{k}={v}" for k, v in meta.items()))


if __name__ == "__main__":
    main()
