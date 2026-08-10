#!/usr/bin/env python3
# Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
# SPDX-License-Identifier: GPL-2.0
"""
A depthwise conv whose CORRECT OUTPUT NAMES THE LAYOUT.

The coefficient surface is exonerated. Rounds 57 and 58 swept the OUT_CVT
shift, A on its own from 2^-7 to 2^7, and C on the depthwise path, and the
COMPUTED count never left 1 on mn_dw1 or 2 on mn_dw25, while the same knobs
visibly break or move a regular conv. Everything in the record is verified
against the vendor capture anyway: A and C at 32 of 32 channels, the 48 byte
stride, the weight lanes 288 of 288, the fourteen registers. The depthwise conv
fires on every channel and computes the wrong number, and no scalar this driver
writes changes which number.

So the remaining suspect is which INPUT each multiply gets, and a random model
cannot see that: every wrong answer looks like a wrong answer. An impulse can.

Each channel gets a single 1.0 tap at position c mod 9 and zeros elsewhere. The
correct output of channel c is then the input to channel c, shifted by that
tap's offset, and reading the hardware's output says directly:

  right shift, right channel     the tap map and the channel map are both right
  right shift, wrong channel     the channels are permuted, which is the live
                                 suspicion since the weight buffer packs them
                                 in PAIRS and CNA 0x1024 says 1 rather than 31
  wrong shift, right channel     ky and kx are transposed or the plane order is
  a blend of several taps        more than one tap is landing on a channel, so
                                 the 4 byte group is being read as 4 weights
                                 rather than 2 weights and 2 zero points

Nine taps and 32 channels means every tap position is exercised three times
over, so a single run distinguishes all four.

⚠ The bias is zero and the weights are exactly representable, so the reference
is not a quantisation approximation: with an impulse the output IS the input,
and any disagreement is a layout fact rather than a rounding one.
"""
import os

import numpy as np
import tensorflow as tf

SCR = os.path.dirname(os.path.abspath(__file__))
HW, C, K = 32, 32, 3


def main():
    inp = tf.keras.Input([HW, HW, C])
    y = tf.keras.layers.DepthwiseConv2D(K, padding="same", use_bias=True)(inp)
    m = tf.keras.Model(inp, y)

    w = np.zeros((K, K, C, 1), dtype=np.float32)
    for c in range(C):
        w[(c % 9) // 3, (c % 9) % 3, c, 0] = 1.0
    m.layers[1].set_weights([w, np.zeros(C, dtype=np.float32)])

    # The calibration range has to cover the output too, and with an impulse
    # the output range IS the input range, so one ramp does both.
    def rep():
        for s in range(20):
            v = (((np.arange(HW * HW * C) + s * 13) % 255) - 127) * 0.01
            yield [v.astype(np.float32).reshape(1, HW, HW, C)]

    conv = tf.lite.TFLiteConverter.from_keras_model(m)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep
    conv.inference_input_type = tf.uint8
    conv.inference_output_type = tf.uint8
    tfl = conv.convert()
    out = f"{SCR}/dw_imp.tflite"
    open(out, "wb").write(tfl)
    print(f"wrote {out}, {len(tfl)} bytes")

    it = tf.lite.Interpreter(model_content=tfl)
    it.allocate_tensors()
    print("  ops:", [o["op_name"] for o in it._get_ops_details()])
    for d in it.get_input_details() + it.get_output_details():
        print(f"  {d['name']} {d['shape']} {d['dtype'].__name__} "
              f"scale {d['quantization'][0]:.8f} zp {d['quantization'][1]}")
    print("  tap per channel (ky, kx):",
          [((c % 9) // 3, (c % 9) % 3) for c in range(8)], "...")


if __name__ == "__main__":
    main()
