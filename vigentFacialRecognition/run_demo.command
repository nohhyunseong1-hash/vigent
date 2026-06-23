#!/bin/bash
# VIGENT 얼굴 인식 웹캠 데모 — 더블클릭 실행
# 서버를 띄우고 브라우저를 연다. 종료는 이 창에서 Ctrl+C.
cd "$(dirname "$0")/.."          # VIGENT 루트로 이동
PY="$(command -v python3 || echo /opt/anaconda3/bin/python3)"
echo "VIGENT 얼굴 인식 데모를 시작합니다..."
"$PY" -m vigentFacialRecognition.download_models   # 모델 없으면 받기(있으면 건너뜀)
"$PY" -m vigentFacialRecognition.demo_server
