#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT 웹캠 수집 — 더블클릭 실행(터미널이 카메라 권한 팝업을 띄움)
#  Phase 0: 웹캠 벤치 평가셋을 태그별로 자동 캡처
# ════════════════════════════════════════════════════════════
cd "$HOME/Desktop/VIGENT" || { echo "[오류] VIGENT 폴더 없음"; read -r; exit 1; }

PY=""
for c in /opt/anaconda3/bin/python3 python3 /usr/local/bin/python3; do
  if "$c" -c "import cv2" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] opencv(cv2) 설치된 python3 없음. pip install opencv-python 후 재시도."
  read -r -p "엔터로 종료..."; exit 1
fi

echo "════════════════════════════════════════════════"
echo "  VIGENT 웹캠 수집"
echo "  · 첫 실행 시 '카메라 접근 허용' 팝업 → 반드시 허용"
echo "  · 태그 예:  neg_empty / neg_monitor / neg_desk / neg_light"
echo "             pos_bare_near / pos_hardhat_mid / pos_combo_far  (pos_<상태>_<거리>)"
echo "  · 상태: bare hardhat vest mask combo   거리: near mid far"
echo "  · 끝내려면 태그에 그냥 엔터"
echo "════════════════════════════════════════════════"

while true; do
  echo ""
  read -r -p "장면 태그 (끝내려면 엔터): " TAG
  [ -z "$TAG" ] && break
  read -r -p "  장수 (기본 12): " N;  N=${N:-12}
  read -r -p "  시작 대기초 (기본 5, 자리비우기/포즈): " CD;  CD=${CD:-5}
  "$PY" benchmarks/webcam_capture.py --tag "$TAG" --count "$N" --interval 1 --countdown "$CD"
done

echo ""
echo "수집 종료. raw/ 현황:"
ls data/datasets/webcam_bench/raw/ 2>/dev/null | sed 's/_[0-9]*\.jpg//' | sort | uniq -c
read -r -p "엔터로 닫기..."
