#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT Safety — 바탕화면 더블클릭 실행기
#  (종료: 이 터미널 창을 닫거나 Control+C)
#  하는 일: 서버 시작(또는 이미 켜져 있으면 그대로) → 브라우저로 /safety 열기
# ════════════════════════════════════════════════════════════
DIR="$HOME/Desktop/VIGENT"
PORT=8010
URL="http://127.0.0.1:${PORT}/safety-local?t=$(date +%s)"

echo "================================================"
echo "  VIGENT Safety 시작..."
echo "================================================"

if [ ! -d "$DIR/vigent-core" ]; then
  echo "[오류] VIGENT 폴더를 찾지 못했습니다: $DIR"
  read -r -p "엔터로 종료..." _ ; exit 1
fi

# uvicorn/fastapi 가 설치된 파이썬 자동 탐색
PY=""
for c in python3 /opt/anaconda3/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] uvicorn/fastapi 가 설치된 python3 를 찾지 못했습니다."
  echo "      터미널에서  pip install fastapi uvicorn opencv-python ultralytics pyyaml  실행 후 다시 시도."
  read -r -p "엔터로 종료..." _ ; exit 1
fi
echo "사용 파이썬: $PY"

# 이미 서버가 떠 있으면 브라우저만 연다
if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/health"; then
  echo "서버가 이미 동작 중 → 페이지를 엽니다."
  open "$URL"; exit 0
fi

lsof -ti tcp:${PORT} 2>/dev/null | xargs kill -9 2>/dev/null
cd "$DIR/vigent-core" || { echo "[오류] 폴더 없음: $DIR/vigent-core"; read -r _; exit 1; }

echo "서버 시작 중 (최대 30초)..."
"$PY" -m uvicorn main:app --host 127.0.0.1 --port ${PORT} --reload --reload-dir "$DIR/vigent-core" &
SRV=$!
for i in $(seq 1 30); do
  curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" && break
  sleep 1
done
open "$URL"
echo "------------------------------------------------"
echo " 관제 화면:  http://127.0.0.1:${PORT}/safety-local  (로컬판·CDN 불필요)"
echo " 이 창을 닫으면 서버가 종료됩니다."
echo "------------------------------------------------"
wait $SRV
