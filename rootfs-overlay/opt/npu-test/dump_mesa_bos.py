#!/usr/bin/env python3
"""
Print the Mesa ROCKET_DEBUG=dump_bos buffers as TEXT, in the same "cap: BO"
format the instrumented vendor kernel prints, so the Mesa payload comes back
over the SERIAL CONSOLE (no USB / no binary file transfer needed) and can be
diffed against the vendor dump line-for-line.

Windows + hex-head sizes match the vendor kernel (rknpu_job.c rknpu_cap_dump_bo)
so distinct/nonzero are directly comparable:
    weights win=16384 hex=2048 ; input/output win=4096 hex=512 ; bias win=1024 hex=512

Usage: dump_mesa_bos.py <dumpdir>   (default /tmp/dump)
"""
import glob
import os
import sys

DUMPDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/dump"

# name -> (mesa file glob, stat window, hex-head bytes)
BOS = [
    ("weights", "mesa-weights-*.bin", 16384, 2048),
    ("input", "mesa-input-*.bin", 4096, 512),
    ("bias", "mesa-biases-*.bin", 1024, 512),
    ("output", "mesa-output-*.bin", 4096, 512),
]


def dump(name, data, win, hexlen):
    w = data[:win]
    distinct = len(set(w))
    nonzero = sum(1 for b in w if b)
    print(f"mesa cap: BO {name:<7} len={len(w)} distinct={distinct} "
          f"nonzero={nonzero} filesize={len(data)}")
    for off in range(0, min(len(data), hexlen), 16):
        row = data[off:off + 16]
        hx = " ".join(f"{b:02x}" for b in row)
        print(f"mesa cap: BO {name:<7} +{off:04x}: {hx}")


print("########## MESA BO TEXT DUMP (for serial diff) ##########")
for name, pat, win, hexlen in BOS:
    hits = sorted(glob.glob(os.path.join(DUMPDIR, pat)))
    if not hits:
        print(f"mesa cap: BO {name:<7} <{pat} not found in {DUMPDIR}>")
        continue
    data = open(hits[0], "rb").read()
    if len(hits) > 1:
        print(f"mesa cap: BO {name:<7} NOTE {len(hits)} files, using "
              f"{os.path.basename(hits[0])}")
    dump(name, data, win, hexlen)
print("########## END MESA BO TEXT DUMP ##########")
