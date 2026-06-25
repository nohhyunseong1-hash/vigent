#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT Safety — 더블클릭 실행기
#  (종료: 이 터미널 창을 닫거나 Control+C)
#  하는 일: 헬스체크 → (필요시) 서버 재시작 → 브라우저로 /safety 열기
# ════════════════════════════════════════════════════════════
DIR="$HOME/Desktop/VIGENT"
PORT=8010
# AX 인식 엔진 + VIGENT 콘솔 화면(체감이 가장 좋음). rf-detr 버전은 /safety-pro 로 접근 가능.
URL="http://127.0.0.1:${PORT}/safety?t=$(date +%s)"

echo "================================================"
echo "  VIGENT Safety 테마 시작..."
echo "================================================"

# uvicorn/fastapi 가 설치된 파이썬을 자동으로 찾는다
PY=""
for c in python3 /opt/anaconda3/bin/python3 /usr/local/bin/python3; do
  if "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] uvicorn/fastapi 가 설치된 python3 를 찾지 못했습니다."
  echo "      터미널에서  pip install fastapi uvicorn  실행 후 다시 시도하세요."
  read -r; exit 1
fi
echo "사용 파이썬: $PY"

# 이미 우리 서버가 떠 있으면(=/safety 200) 그대로 브라우저만 연다
if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/health"; then
  echo "서버가 이미 정상 동작 중 → 페이지를 엽니다."
  open "$URL"; exit 0
fi

# 포트에 옛/다른 프로세스가 있으면 정리(이 포트는 VIGENT 전용으로 사용)
lsof -ti tcp:${PORT} | xargs kill -9 2>/dev/null

# 폴더명에 하이픈이 있어 'vigent-core' 안으로 들어가 main:app 으로 실행한다
cd "$DIR/vigent-core" || { echo "[오류] 폴더 없음: $DIR/vigent-core"; read -r; exit 1; }

echo "서버 시작 중 (최대 30초 대기)..."
# --reload: main.py 등 파이썬 코드를 저장하면 서버가 자동 재시작(수동 재시작 불필요).
#           화면 파일(html/js)은 원래 새로고침만으로 반영됨.
"$PY" -m uvicorn main:app --host 127.0.0.1 --port ${PORT} --reload --reload-dir "$DIR/vigent-core" &
SRV=$!

# /safety 가 200 으로 응답할 때까지 대기
for i in $(seq 1 30); do
  curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" && break
  sleep 1
done

open "$URL"
echo "------------------------------------------------"
echo "페이지를 열었습니다 → http://127.0.0.1:${PORT}/safety"
echo "이 창을 닫으면 서버가 종료됩니다."
echo "------------------------------------------------"
wait $SRV
