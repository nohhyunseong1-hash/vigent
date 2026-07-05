#!/bin/bash
# VIGENT 크로스플랫폼 런처 (C-S2). macOS/Linux 공통. .command(개발 편의)와 별개.
#   사용:  ./run.sh              # 로컬 개발(127.0.0.1, 무토큰)
#          VIGENT_HOST=0.0.0.0 VIGENT_API_TOKEN=secret ./run.sh   # 외부 노출(토큰 필수)
# 설정은 전부 환경변수(하드코딩 없음): VIGENT_HOST / VIGENT_PORT / VIGENT_API_TOKEN / VIGENT_EDGE
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${VIGENT_PORT:-8010}"
export VIGENT_HOST="${VIGENT_HOST:-127.0.0.1}"

# uvicorn/fastapi 가 설치된 파이썬 탐색
PY=""
for c in python3 python /opt/anaconda3/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[오류] uvicorn/fastapi 가 설치된 python 을 찾지 못했습니다. pip install -r requirements.txt 후 재시도." >&2
  exit 1
fi

echo "VIGENT 시작: host=${VIGENT_HOST} port=${PORT} (python: $PY)"
cd "$DIR/vigent-core"
exec "$PY" -m uvicorn main:app --host "${VIGENT_HOST}" --port "${PORT}"
