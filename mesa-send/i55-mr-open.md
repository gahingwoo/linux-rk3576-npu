@tomeuv It is up as https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/43804

Five patches, 648 lines, no environment variables, rebased on today's main. One
regular uint8 per tensor convolution on RK3576, and depthwise, pointwise and
MobileNet's first layer are declined so they fall back to the CPU.
