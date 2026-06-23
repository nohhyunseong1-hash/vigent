#!/bin/bash
# ════════════════════════════════════════════════════════════
#  VIGENT 엣지/USB 설치본 — 헤드리스 실행기
#  하는 일: site.yaml 의 카메라들을 부팅 시 자동 감시(브라우저 불필요).
#           위험 감지 → 자동처리 콘솔(/safety/auto)에 자동 기록.
#  사용: ① cp config/site.example.yaml config/site.yaml  후 카메라 주소 수정
#        ② 이 파일 실행(더블클릭 또는: bash bin/vigent-edge.command)
#  (Linux/Jetson 박스에서도 동일하게: bash bin/vigent-edge.command)
# ════════════════════════════════════════════════════════════
DIR="$(cd "$(dirname "$0")/.." && pwd)"     # 프로젝트 루트(스크립트 위치 기준 — USB 어디 꽂혀도 동작)
PORT="${VIGENT_PORT:-8010}"

echo "================================================"
echo "  VIGENT 엣지 설치본 시작 (헤드리스)"
echo "  프로젝트: $DIR"
echo "================================================"

# 현장 설정 확인
if [ ! -f "$DIR/config/site.yaml" ]; then
  echo "[안내] config/site.yaml 이 없습니다."
  echo "       먼저:  cp config/site.example.yaml config/site.yaml  후 카메라 주소를 수정하세요."
  read -r -p "엔터를 누르면 종료합니다..." _ ; exit 1
fi

# uvicorn/fastapi 가 설치된 파이썬 자동 탐색
PY=""
for c in python3 /opt/anaconda3/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] uvicorn/fastapi 가 설치된 python3 를 찾지 못했습니다."
  echo "      pip install fastapi uvicorn opencv-python ultralytics pyyaml  후 다시 시도하세요."
  read -r -p "엔터를 누르면 종료합니다..." _ ; exit 1
fi
echo "사용 파이썬: $PY"

# 포트에 옛 프로세스가 있으면 정리
lsof -ti tcp:${PORT} 2>/dev/null | xargs kill -9 2>/dev/null

cd "$DIR/vigent-core" || { echo "[오류] 폴더 없음: $DIR/vigent-core"; read -r _; exit 1; }

# VIGENT_EDGE=1 → 부팅 시 site.yaml 카메라로 워커 자동시작(startup 이벤트)
export VIGENT_EDGE=1
echo "현장 카메라 자동 감시 시작 중... (Ctrl+C 로 종료)"
echo "상태 확인:  http://127.0.0.1:${PORT}/workers"
echo "관제 콘솔:  http://127.0.0.1:${PORT}/safety/auto"
echo "------------------------------------------------"
exec "$PY" -m uvicorn main:app --host 0.0.0.0 --port ${PORT}
