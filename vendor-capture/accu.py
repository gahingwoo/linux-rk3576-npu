#!/usr/bin/env python3
import sys
from rknn.api import RKNN
rknn = RKNN(verbose=False)
# raw uint8 input (infer.py feeds the resized RGB image straight in, no norm)
rknn.config(mean_values=[[0,0,0]], std_values=[[1,1,1]], target_platform='rk3576')
if rknn.load_tflite(model='mobilenet_v1_1.0_224_quant.tflite') != 0:
    print('load failed'); sys.exit(1)
if rknn.build(do_quantization=True, dataset='ds_gh.txt') != 0:
    print('build failed'); sys.exit(1)
# accuracy_analysis dumps per-layer golden(fp) + simulated(quant) tensors
r = rknn.accuracy_analysis(inputs=['grace_hopper.jpg'], output_dir='snapshot_gh',
                           target=None)
print('accuracy_analysis ret =', r)
rknn.release()
