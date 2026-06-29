import os; SCR=os.path.dirname(os.path.abspath(__file__))
import numpy as np, tensorflow as tf
# ONE standalone depthwise conv, uint8 I/O (conv2d-cal's PROVEN regime) -> isolate
# the depthwise COMPUTE (MobileNet's break = layer1 depthwise outputs zero on a real
# input). If this standalone dw computes (maxdiff small) the MobileNet break is the
# chained input layout (conv0 out vs dw in); if it ALSO zeros, the dw datapath itself
# is broken. depth_multiplier=1, 3x3 same (MobileNet dw shape).
HW,C=40,16
inp=tf.keras.Input([HW,HW,C])
y=tf.keras.layers.DepthwiseConv2D(3,padding='same',use_bias=True)(inp)
m=tf.keras.Model(inp,y)
rng=np.random.RandomState(0)
# depthwise kernel shape (3,3,C,1); small so output is non-saturating
m.layers[1].set_weights([(rng.randn(3,3,C,1)*0.08).astype(np.float32),
                         (rng.randn(C)*0.05).astype(np.float32)])
def rep():
    for s in range(40):
        yield [((((np.arange(1*HW*HW*C)+s*13)%255)-127)*0.01).astype(np.float32).reshape(1,HW,HW,C)]
c=tf.lite.TFLiteConverter.from_keras_model(m)
c.optimizations=[tf.lite.Optimize.DEFAULT]
c.representative_dataset=rep
c.inference_input_type=tf.uint8; c.inference_output_type=tf.uint8
tfl=c.convert()
open(f"{SCR}/dwconv.tflite","wb").write(tfl)
print("wrote dwconv.tflite", len(tfl),"bytes")
it=tf.lite.Interpreter(model_content=tfl); it.allocate_tensors()
print("  ops:", [o['op_name'] for o in it._get_ops_details()])
i=it.get_input_details()[0]; o=it.get_output_details()[0]
print(f"  IN  {i['dtype'].__name__} zp={i['quantization'][1]} sc={round(i['quantization'][0],5)}")
print(f"  OUT {o['dtype'].__name__} zp={o['quantization'][1]} sc={round(o['quantization'][0],5)}")
x=((np.arange(int(np.prod(i['shape'])))%255).astype(i['dtype'])).reshape(i['shape'])
it.set_tensor(i['index'],x); it.invoke()
out=it.get_tensor(o['index']).flatten().astype(int)
print(f"  OUTPUT distinct={len(np.unique(out))} min={out.min()} max={out.max()} (non-saturating if >>4)")
