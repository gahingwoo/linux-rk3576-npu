#!/usr/bin/env python3
"""
Resize a 1x1 conv's spatial dimensions. Weights are unaffected: a 1x1 kernel is
valid at any height and width.

Why: the padding fix made cal_s1 compute, so two geometries now work and both
are 5x5, 16 in / 128 out, 80x80, one task. Every remaining failure differs in
more than one way. md003 is the closest thing to a minimal contrast, being 1x1
with 16 in and 16 out, but it sits at 160x160 where the op tiles into two row
windows. Shrinking it to 80x80 removes the tiling and leaves the kernel as
nearly the only difference from a model that works.

Usage: mutate_hw.py <in.tflite> <out.tflite> <hw>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst, hw = sys.argv[1], sys.argv[2], int(sys.argv[3])

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]

    for t in sg.tensors:
        data = model.buffers[t.buffer].data
        if data is not None and len(data):
            continue                      # a constant: weights or bias
        if t.shape is None or len(t.shape) != 4:
            continue
        old = list(t.shape)
        t.shape = [old[0], hw, hw, old[3]]
        print(f"  {old} -> {list(t.shape)}")

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(b.Output()))
    print(f"wrote {dst}")


main()
