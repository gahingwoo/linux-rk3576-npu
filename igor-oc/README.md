# Igor's output-channel probe

Two files received off-list from Igor Paunovic <royalnet026@gmail.com> on
2026-08-17, stored here as sent, with one change to mk1x1.py noted below. Licences are his:

  mk1x1.py    MIT,       (c) 2026 Igor Paunovic
  oc_perch.py GPL-2.0,   derived from perch.py by Jiaxing Hu

`mk1x1.py` builds a quantised TFLite CONV_2D 1x1, 64 input channels, N output
channels, by writing the flatbuffer by hand (the tflite pip package is a reader
only). `oc_perch.py` scores the teflon delegate against the CPU interpreter per
output channel against the RAW reference.

Two guards in them are the reason they are worth using rather than rolling our
own: the generator refuses to emit a model with a constant output channel,
because such a channel matches trivially, and the scorer never compares against
max(cpu, zero_point), because clamping the reference hides a difference on one
side and invents one on the other.

His RK3588 reference point, upstream Mesa, oc = 48:

    48 of 48 within 1, 40 bit exact, saturation 8.9%, no constant reference
    channels

WHY THIS MATTERS HERE: `0x4050` was fitted on ten vendor models at oc = 16..160
in steps of 16, and at every multiple of 16 the two candidate rules,
DIV_ROUND_UP(oc,16) parity and oc mod 32, give the same answer. They disagree
only at output channel counts that are NOT multiples of 16, and nobody has ever
built one. mk1x1.py builds them.

The only edit: mk1x1.py's generation loop is under `if __name__ == "__main__":`
so `build()` can be imported. The host here has numpy, flatbuffers and the
tflite schema package but no tflite_runtime, so the models are built here and
his `verify_cpu` guard runs on the board instead, where oc_perch.py prints the
same constant-channel count on every scored model.
