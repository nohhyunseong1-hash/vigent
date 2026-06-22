#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT Sports — 요가/필라테스 폼 코치
#  (종료: 이 터미널 창을 닫거나 Control+C)
# ════════════════════════════════════════════════════════════
DIR="$HOME/Desktop/VIGENT"; PORT=8010
URL="http://127.0.0.1:${PORT}/sports?t=$(date +%s)"
echo "================================================"
echo "  VIGENT Sports (요가/필라테스) 시작..."
echo "================================================"
PY=""
for c in python3 /opt/anaconda3/bin/python3 /usr/local/bin/python3; do
  if "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "[오류] uvicorn/fastapi python 없음"; read -r; exit 1; }
echo "사용 파이썬: $PY"
if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/health"; then
  echo "서버 이미 동작 중 → 페이지 엽니다."; open "$URL"; exit 0; fi
lsof -ti tcp:${PORT} | xargs kill -9 2>/dev/null
cd "$DIR/vigent-core" || { echo "[오류] 폴더 없음"; read -r; exit 1; }
echo "서버 시작 중 (최대 30초)..."
"$PY" -m uvicorn main:app --host 127.0.0.1 --port ${PORT} &
SRV=$!
for i in $(seq 1 30); do curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" && break; sleep 1; done
open "$URL"
echo "------------------------------------------------"
echo "페이지 열림 → /sports · 웹캠 허용하고 동작을 선택하세요."
echo "이 창을 닫으면 서버가 종료됩니다."
echo "------------------------------------------------"
wait $SRV
