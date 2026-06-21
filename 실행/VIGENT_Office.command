#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT Office — 사무직 자세교정 도우미 (복지)
#  (종료: 이 터미널 창을 닫거나 Control+C)
#  하는 일: 헬스체크 → (필요시) 서버 시작 → 브라우저로 /office 열기
#  화면: 웹캠으로 앉은 자세를 보고 목·허리·어깨 점수+코칭 (얼굴 블러·익명)
# ════════════════════════════════════════════════════════════
DIR="$HOME/Desktop/VIGENT"
PORT=8010
URL="http://127.0.0.1:${PORT}/office?t=$(date +%s)"

echo "================================================"
echo "  VIGENT Office (자세교정 복지) 시작..."
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

# 이미 서버가 떠 있으면 그대로 브라우저만 연다(safety 와 같은 서버 공유)
if curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/health"; then
  echo "서버가 이미 정상 동작 중 → 페이지를 엽니다."
  open "$URL"; exit 0
fi

# 포트에 옛/다른 프로세스가 있으면 정리
lsof -ti tcp:${PORT} | xargs kill -9 2>/dev/null

cd "$DIR/vigent-core" || { echo "[오류] 폴더 없음: $DIR/vigent-core"; read -r; exit 1; }

echo "서버 시작 중 (최대 30초 대기)..."
"$PY" -m uvicorn main:app --host 127.0.0.1 --port ${PORT} &
SRV=$!

for i in $(seq 1 30); do
  curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" && break
  sleep 1
done

open "$URL"
echo "------------------------------------------------"
echo "페이지를 열었습니다 → http://127.0.0.1:${PORT}/office"
echo "웹캠 권한을 허용하고 바르게 앉아보세요. 얼굴은 자동 블러됩니다."
echo "이 창을 닫으면 서버가 종료됩니다."
echo "------------------------------------------------"
wait $SRV
