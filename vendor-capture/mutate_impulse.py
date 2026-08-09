#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
Replace a conv's kernel with impulses, one tap position per output channel.

Why: for a 3x3 conv cropped from the model that computes, everything is now
verified. The regcmd matches the vendor in absolute terms, the weight layout
matches including the 32-channel grouping, the CMAC does read the weight buffer
and the DPU does read the coefficients, and the result is still out_zp plus a
couple of counts. That is what you get when each weight is multiplied by the
wrong input pixel: over 144 taps the products cancel toward zero.

An impulse kernel makes that visible. Output channel c gets a single live tap at
spatial position (c / k, c % k) and the weight zero point everywhere else, so a
correct convolution reproduces the input, shifted by that tap:

    out[y][x] = in[stride*y + ky - pad_top][stride*x + kx - pad_left]

Reading which shift the hardware actually produced, per output channel, says
exactly which input pixel it paired each tap with. If the shifts are right the
pairing is fine and the cancellation is elsewhere; if they are wrong, the offset
is the bug, in units of pixels.

Only input channel 0 is live, so the other channels cannot mask the result.
Per-tensor quantization keeps this a valid model.

Usage: mutate_impulse.py <in.tflite> <out.tflite>
"""
import sys

import flatbuffers
from tensorflow.lite.python import schema_py_generated as sch


def main():
    src, dst = sys.argv[1], sys.argv[2]

    buf = bytearray(open(src, "rb").read())
    model = sch.ModelT.InitFromObj(sch.Model.GetRootAsModel(buf, 0))
    sg = model.subgraphs[0]
    op = sg.operators[0]
    w = sg.tensors[op.inputs[1]]
    oc, kh, kw, ic = (int(x) for x in w.shape)

    zp = int(w.quantization.zeroPoint[0])
    # A live tap has to be far from the zero point to dominate, and stay inside
    # the byte range the tensor's own scale covers.
    live = 255 if zp < 128 else 0
    print(f"  weights {oc}x{kh}x{kw}x{ic}, wt_zp {zp}, live tap value {live}")

    data = bytearray([zp]) * (oc * kh * kw * ic)
    used = []
    for o in range(oc):
        t = o % (kh * kw)
        ky, kx = t // kw, t % kw
        data[((o * kh + ky) * kw + kx) * ic + 0] = live
        if o < kh * kw:
            used.append((o, ky, kx))
    model.buffers[w.buffer].data = list(data)
    print("  output channel -> live tap (ky, kx):",
          ", ".join(f"{o}->({y},{x})" for o, y, x in used))

    # ⚠ Rescale the output. One live tap carries about 1/(k*k*ic) of the
    # dynamic range the original kernel had, and leaving the output scale alone
    # makes the result underflow the requant to the zero point: the first
    # version of this probe returned a flat out_zp for BOTH kernel sizes, which
    # is why its control failed. Set the output scale from the largest product a
    # single tap can produce so the answer uses the byte range.
    it = sg.tensors[op.inputs[0]]
    ot = sg.tensors[op.outputs[0]]
    in_s = float(it.quantization.scale[0])
    in_zp = int(it.quantization.zeroPoint[0])
    wt_s = float(w.quantization.scale[0])
    peak = max(255 - in_zp, in_zp) * in_s * abs(live - zp) * wt_s
    old_os = float(ot.quantization.scale[0])
    ot.quantization.scale = [peak / 120.0]
    print(f"  output scale {old_os:g} -> {peak / 120.0:g} "
          f"(single tap peak {peak:g})")

    b = flatbuffers.Builder(1024)
    b.Finish(model.Pack(b), file_identifier=b"TFL3")
    open(dst, "wb").write(bytes(b.Output()))
    print(f"wrote {dst}")


main()
