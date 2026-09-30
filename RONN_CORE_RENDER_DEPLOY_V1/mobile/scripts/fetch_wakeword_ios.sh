#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODULE="$ROOT/modules/ronn-wake-word/ios"
VENDOR="$MODULE/Vendor"
RESOURCES="$MODULE/Resources"
TMP="${TMPDIR:-/tmp}/ronn-wakeword-assets"

mkdir -p "$VENDOR/SherpaOnnx" "$VENDOR/OnnxRuntime" "$RESOURCES" "$TMP"

download_and_verify() {
  local url="$1"
  local sha="$2"
  local out="$3"
  if [ -f "$out" ]; then return; fi
  curl -fL --retry 4 --retry-delay 2 "$url" -o "$out"
  echo "$sha  $out" | shasum -a 256 -c -
}

SHERPA_ZIP="$TMP/sherpa-onnx-ios.zip"
ONNX_ZIP="$TMP/onnxruntime-ios.zip"
download_and_verify "https://github.com/k2-fsa/sherpa-onnx/releases/download/xcframework/sherpa-onnx-v1.13.8-ios-static.xcframework.zip" "6b8e769cb153343270fdccbe92e3b3db0d1c421d67fa0989ab01fdf5b2fcf2de" "$SHERPA_ZIP"
download_and_verify "https://github.com/csukuangfj/onnxruntime-libs/releases/download/v1.28.2/onnxruntime-ios-static-xcframework-1.28.2.xcframework.zip" "2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599" "$ONNX_ZIP"

if [ ! -d "$VENDOR/SherpaOnnx/sherpa-onnx.xcframework" ]; then
  rm -rf "$VENDOR/SherpaOnnx" && mkdir -p "$VENDOR/SherpaOnnx"
  unzip -q "$SHERPA_ZIP" -d "$VENDOR/SherpaOnnx"
fi
if [ ! -d "$VENDOR/OnnxRuntime/onnxruntime.xcframework" ]; then
  rm -rf "$VENDOR/OnnxRuntime" && mkdir -p "$VENDOR/OnnxRuntime"
  unzip -q "$ONNX_ZIP" -d "$VENDOR/OnnxRuntime"
fi

MODEL_BASE="https://huggingface.co/openEuler/sherpa-kws/resolve/main/assets"
download_model() {
  local remote="$1"
  local out="$2"
  local sha="$3"
  if [ ! -s "$out" ]; then curl -fL --retry 4 --retry-delay 2 "$remote" -o "$out"; fi
  echo "$sha  $out" | shasum -a 256 -c -
}
download_model "$MODEL_BASE/onnx/encoder.onnx?download=true" "$RESOURCES/ronn-kws-encoder.onnx" "540ff509ed89bd22afe04bf7049a54bb1c95c6d8a18742ea9691910cdb5f859e"
download_model "$MODEL_BASE/onnx/decoder.onnx?download=true" "$RESOURCES/ronn-kws-decoder.onnx" "63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21"
download_model "$MODEL_BASE/onnx/joiner.onnx?download=true" "$RESOURCES/ronn-kws-joiner.onnx" "76f7a24ed0c08633af14b2ee377f747af880d3b65eeba2cd3f31f3380fb73e8d"
download_model "$MODEL_BASE/tokens.txt?download=true" "$RESOURCES/ronn-kws-tokens.txt" "2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0"

for required in "$VENDOR/SherpaOnnx/sherpa-onnx.xcframework" "$VENDOR/OnnxRuntime/onnxruntime.xcframework" "$RESOURCES/ronn-kws-encoder.onnx" "$RESOURCES/ronn-kws-decoder.onnx" "$RESOURCES/ronn-kws-joiner.onnx" "$RESOURCES/ronn-kws-tokens.txt"; do
  [ -e "$required" ] || { echo "[RONN_WAKE] Missing $required"; exit 1; }
done
echo "[RONN_WAKE] Offline wake-word assets ready."
