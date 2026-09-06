#!/bin/bash
# VIGENT + Tapo(IP카메라) — go2rtc로 RTSP를 브라우저용 변환 후 VIGENT 화면에서 보기
# 종료: 이 창 닫기 / Ctrl+C
DIR="$HOME/Desktop/VIGENT"; PORT=8010
export RTSP_URL="$(grep '^RTSP_URL=' "$DIR/.env" | head -1 | cut -d= -f2-)"
[ -z "$RTSP_URL" ] && { echo "❌ .env 에 RTSP_URL 없음 (Tapo 주소부터 설정하세요)"; read -r; exit 1; }
PY=""; for c in python3 /opt/anaconda3/bin/python3; do "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1 && PY="$c" && break; done
[ -z "$PY" ] && { echo "❌ python 없음"; read -r; exit 1; }

echo "1) go2rtc 시작(Tapo→브라우저 변환)..."
"$DIR/bin/go2rtc" -config "$DIR/config/go2rtc.yaml" >/tmp/go2rtc.log 2>&1 &
GPID=$!
echo "2) VIGENT 서버 시작..."
lsof -ti tcp:${PORT} | xargs kill -9 2>/dev/null
( cd "$DIR/vigent-core" && "$PY" -m uvicorn main:app --host 127.0.0.1 --port ${PORT} >/tmp/vigent.log 2>&1 ) &
SRV=$!
for i in $(seq 1 30); do curl -fs -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/health" && break; sleep 1; done
echo "3) 브라우저 열기 → Tapo 영상으로 VIGENT 화면"
open "http://127.0.0.1:${PORT}/safety?cam=tapo&t=$(date +%s)"
echo "--- 이 창을 닫으면 go2rtc·서버가 종료됩니다 ---"
trap "kill $GPID $SRV 2>/dev/null" EXIT
wait $SRV
