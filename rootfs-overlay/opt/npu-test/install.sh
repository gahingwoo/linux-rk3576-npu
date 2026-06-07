#!/usr/bin/env sh
# On-board first-run setup: install tflite-runtime and fetch model.
set -e

pip3 install --upgrade tflite-runtime==2.14.0

MODEL_DIR="/opt/npu-test"
if [ ! -f "${MODEL_DIR}/mobilenet_v1_1.0_224_quant.tflite" ]; then
    echo "Fetching MobileNetV1 UINT8 model..."
    URL="https://storage.googleapis.com/download.tensorflow.org/models/mobilenet_v1_2018_08_02/mobilenet_v1_1.0_224_quant.tgz"
    wget -q -O /tmp/mobilenet.tgz "$URL" || curl -sL -o /tmp/mobilenet.tgz "$URL"
    tar -xzf /tmp/mobilenet.tgz -C "$MODEL_DIR"
    rm /tmp/mobilenet.tgz
fi

echo "Setup complete. Run: bash /opt/npu-test/bringup-check.sh"
