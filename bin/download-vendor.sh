#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT 로컬 번들 자산 다운로드(MediaPipe·TF.js)
#  → vigent-core/static/vendor/ 에 받아 두면 /safety-local 이 CDN 없이(폐쇄망·USB) 동작.
#  사용:  bash bin/download-vendor.sh
#  (인터넷 있는 곳에서 1회 실행 → 이후 폐쇄망에서도 작동)
# ════════════════════════════════════════════════════════════
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
V="$SRC/vigent-core/static/vendor"
mkdir -p "$V/mediapipe" "$V/tf/cocossd" "$V/tf/mobilenet"
dl(){ curl -fsS --max-time 120 "$1" -o "$2" && echo "  OK $(basename "$2")" || echo "  FAIL $1"; }

echo "[1/4] TF.js 라이브러리..."
dl "https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.14.0/dist/tf.min.js" "$V/tf/tf.min.js"
dl "https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js" "$V/tf/coco-ssd.min.js"
dl "https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js" "$V/tf/mobilenet.min.js"

echo "[2/4] MediaPipe Holistic(라이브러리 + 런타임 자산)..."
MPB="https://cdn.jsdelivr.net/npm/@mediapipe/holistic@0.5.1675471629"
for f in holistic.js camera_utils.js drawing_utils.js \
         holistic.binarypb holistic_solution_packed_assets.data holistic_solution_packed_assets_loader.js \
         holistic_solution_simd_wasm_bin.data holistic_solution_simd_wasm_bin.js holistic_solution_simd_wasm_bin.wasm \
         holistic_solution_wasm_bin.js holistic_solution_wasm_bin.wasm \
         pose_landmark_full.tflite pose_landmark_lite.tflite; do
  # camera_utils/drawing_utils 는 별도 패키지 경로
  case "$f" in
    camera_utils.js) dl "https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js" "$V/mediapipe/$f" ;;
    drawing_utils.js) dl "https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js" "$V/mediapipe/$f" ;;
    *) dl "$MPB/$f" "$V/mediapipe/$f" ;;
  esac
done

echo "[3/4] coco-ssd 모델 가중치(ssd_mobilenet_v2)..."
CB="https://storage.googleapis.com/tfjs-models/savedmodel/ssd_mobilenet_v2"
dl "$CB/model.json" "$V/tf/cocossd/model.json"
python3 -c "import json;print('\n'.join(p for w in json.load(open('$V/tf/cocossd/model.json')).get('weightsManifest',[]) for p in w['paths']))" | \
  while read s; do [ -n "$s" ] && dl "$CB/$s" "$V/tf/cocossd/$s"; done

echo "[4/4] mobilenet v2 모델 가중치..."
MB="https://storage.googleapis.com/tfjs-models/savedmodel/mobilenet_v2_1.0_224"
dl "$MB/model.json" "$V/tf/mobilenet/model.json"
python3 -c "import json;print('\n'.join(p for w in json.load(open('$V/tf/mobilenet/model.json')).get('weightsManifest',[]) for p in w['paths']))" | \
  while read s; do [ -n "$s" ] && dl "$MB/$s" "$V/tf/mobilenet/$s"; done

echo "✅ 완료: $V  (용량 $(du -sh "$V" | cut -f1))"
echo "   이제 /safety-local 이 CDN 없이 동작합니다(폐쇄망·USB)."
