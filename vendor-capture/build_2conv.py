import os; SCR=os.path.dirname(os.path.abspath(__file__))
import numpy as np, tensorflow as tf
# Two sequential int8 conv2d ops -> Teflon delegates BOTH as NPU tasks.
# Goal: a REAL 2-task whole-graph job (task_count=2 with two VALID tasks),
# to separate "PC multi-task mode breaks task0" from the force=2 phantom-task
# garbage-clobber confound. Keep outputs non-saturating so maxdiff is the oracle.
HW,IC,M=40,16,16
inp=tf.keras.Input([HW,HW,IC])
y=tf.keras.layers.Conv2D(M,3,padding='same',use_bias=True,activation='relu')(inp)
y=tf.keras.layers.Conv2D(M,3,padding='same',use_bias=True)(y)
m=tf.keras.Model(inp,y)
rng=np.random.RandomState(0)
m.layers[1].set_weights([(rng.randn(3,3,IC,M)*0.06).astype(np.float32),(rng.randn(M)*0.05).astype(np.float32)])
m.layers[2].set_weights([(rng.randn(3,3,M,M)*0.06).astype(np.float32),(rng.randn(M)*0.05).astype(np.float32)])
def rep():
    # centered ~0 so uint8 input zero-point lands ~128 (conv2d-cal's PROVEN-byte-exact
    # in_zp regime), not 0 (the firstconv/image path with its own quirks).
    for s in range(40):
        yield [((((np.arange(1*HW*HW*IC)+s*13)%255)-127)*0.01).astype(np.float32).reshape(1,HW,HW,IC)]
c=tf.lite.TFLiteConverter.from_keras_model(m)
c.optimizations=[tf.lite.Optimize.DEFAULT]
c.representative_dataset=rep
# uint8 I/O (in_zp/out_zp ~128) to match conv2d-cal + test_conv.py's 128-centered input.
c.inference_input_type=tf.uint8; c.inference_output_type=tf.uint8
tfl=c.convert()
open(f"{SCR}/conv2x.tflite","wb").write(tfl)
print("wrote conv2x.tflite", len(tfl),"bytes")
# VERIFY: 2 conv ops + non-saturating final output
it=tf.lite.Interpreter(model_content=tfl); it.allocate_tensors()
ops=[o['op_name'] for o in it._get_ops_details()] if hasattr(it,'_get_ops_details') else []
print("  ops:", ops)
ind=it.get_input_details()[0]; outd=it.get_output_details()[0]
x=((np.arange(int(np.prod(ind['shape'])))%251).astype(ind['dtype'])).reshape(ind['shape'])
it.set_tensor(ind['index'],x); it.invoke()
o=it.get_tensor(outd['index']).flatten().astype(int)
print(f"  in {ind['dtype'].__name__}{list(ind['shape'])} out {outd['dtype'].__name__}{list(outd['shape'])}")
print(f"  OUTPUT distinct={len(np.unique(o))} min={o.min()} max={o.max()} mean={o.mean():.1f} (non-saturating if distinct>>4 and not pinned to one rail)")
