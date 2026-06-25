import os; SCR=os.path.dirname(os.path.abspath(__file__))
import numpy as np, tensorflow as tf
IC,OC,HW=16,128,8
inp=tf.keras.Input([HW,HW,IC])
y=tf.keras.layers.Conv2D(OC,1,use_bias=True)(inp)
m=tf.keras.Model(inp,y)
rng=np.random.RandomState(0)
w=(rng.randn(1,1,IC,OC).astype(np.float32)*0.5)   # HWIO, varied per out-channel
b=(rng.randn(OC).astype(np.float32)*0.1)
m.layers[1].set_weights([w,b])
def rep():
    for s in range(30):
        yield [((np.arange(1*HW*HW*IC)+s*7)%251).astype(np.float32).reshape(1,HW,HW,IC)]
c=tf.lite.TFLiteConverter.from_keras_model(m)
c.optimizations=[tf.lite.Optimize.DEFAULT]
c.representative_dataset=rep
c.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
c.inference_input_type=tf.int8; c.inference_output_type=tf.int8
tfl=c.convert()
open(f"{SCR}/perax_pw.tflite","wb").write(tfl)
print("wrote perax_pw.tflite", len(tfl),"bytes")
# VERIFY: per-axis? + non-saturating output?
it=tf.lite.Interpreter(model_content=tfl); it.allocate_tensors()
for d in it.get_tensor_details():
    q=d['quantization_parameters']; ns=len(q['scales'])
    if ns>1: print(f"  PER-AXIS tensor '{d['name']}' nscales={ns} (qdim ok)")
ind=it.get_input_details()[0]; outd=it.get_output_details()[0]
print("  input",ind['dtype'].__name__,ind['shape'],"output",outd['dtype'].__name__,outd['shape'])
x=((np.arange(int(np.prod(ind['shape'])))%251).astype(ind['dtype'])).reshape(ind['shape'])
it.set_tensor(ind['index'],x); it.invoke()
o=it.get_tensor(outd['index']).flatten().astype(int)
print(f"  OUTPUT distinct={len(np.unique(o))} min={o.min()} max={o.max()} mean={o.mean():.1f} (non-saturating if distinct>>4)")
