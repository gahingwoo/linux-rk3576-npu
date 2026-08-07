#!/usr/bin/env python3
"""
Truncate or repeat a conv's output channels, keeping the kernel and everything
else. Per-tensor quantization makes this safe: the scale and zero point apply to
the whole weight tensor, so a subset or a repeat of the filters is still validly
quantized, and the CPU reference recomputes from the mutated file.

Why: round 5 showed a 1x1 conv fails at 80x80 with one row window, the same size
and channel count where a 5x5 conv computes, so the row-window split is out and
the kernel is in. But the two models also differ in output channels, 16 against
128, and that has never been tested on its own.

  cal_oc16     conv2d-cal cut to 16 output channels. Still 5x5.
  md003_oc128  md003 grown to 128 output channels. Still 1x1.

If cal_oc16 computes and md003_oc128 does not, it is the kernel.

Usage: mutate_oc.py <in.tflite> <out.tflite> <output_channels>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst, want = sys.argv[1], sys.argv[2], int(sys.argv[3])

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]
    op = sg.operators[0]

    w = sg.tensors[op.inputs[1]]
    b = sg.tensors[op.inputs[2]]
    out = sg.tensors[op.outputs[0]]
    oc = w.shape[0]
    per_filter = int(w.shape[1]) * int(w.shape[2]) * int(w.shape[3])

    def resize(tensor, unit_bytes):
        data = bytes(model.buffers[tensor.buffer].data)
        one = len(data) // oc
        assert one == unit_bytes, f"{one} != {unit_bytes}"
        if want <= oc:
            new = data[:want * one]
        else:
            reps = -(-want // oc)
            new = (data * reps)[:want * one]
        model.buffers[tensor.buffer].data = list(new)

    resize(w, per_filter)
    resize(b, 4)
    w.shape = [want] + list(w.shape[1:])
    b.shape = [want]
    out.shape = list(out.shape[:3]) + [want]
    print(f"  output channels {oc} -> {want}, kernel {w.shape[1]}x{w.shape[2]}, "
          f"output {list(out.shape)}")

    bld = flatbuffers.Builder(1024)
    bld.Finish(model.Pack(bld), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(bld.Output()))
    print(f"wrote {dst}")


main()
