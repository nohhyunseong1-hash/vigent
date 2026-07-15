#!/bin/bash
# VIGENT 서버 launcher — launchd KeepAlive 용(F-14 네이티브 크래시 자동 재기동).
#   ※ 표준 uvicorn 기동. VIGENT_EDGE 미설정 = 카메라 자동시작 안 함(개발/데모).
#   ※ exec 로 uvicorn 을 이 프로세스로 치환 → launchd 가 uvicorn PID 를 직접 추적(kill 시 KeepAlive 즉시 재기동).
#
#   ★ 설치 위치 주의(macOS TCC): 이 스크립트가 ~/Desktop 하위에 있으면 launchd 실행 컨텍스트가
#     TCC(개인정보 보호)로 '실행 자체'를 거부한다(Operation not permitted). 따라서 launchd 로 쓸 때는
#     이 파일을 Desktop 밖(예: ~/Library/Application Support/VIGENT/)에 복사하고 VIGENT_ROOT 로
#     프로젝트 경로를 주입한다. (프로젝트 파일 읽기·cd 는 스크립트 실행 후엔 정상 — 실증 F-14 §2.)
set -u
# VIGENT_ROOT 우선(off-Desktop 설치 시 plist 가 주입). 없으면 스크립트 위치 기준(저장소 내 실행).
ROOT="${VIGENT_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
PORT="${VIGENT_PORT:-8010}"
export VIGENT_HOST="${VIGENT_HOST:-127.0.0.1}"

PY=""
for c in /opt/anaconda3/bin/python3 python3 /usr/local/bin/python3 /usr/bin/python3; do
  if "$c" -c "import uvicorn,fastapi" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "[vigent-serve] uvicorn/fastapi python 없음"; exit 1; }

# 포트 선점 정리(전 인스턴스 잔재 소켓) — 크래시 후 재기동 시 안전
lsof -ti tcp:${PORT} 2>/dev/null | xargs kill -9 2>/dev/null

cd "$ROOT/vigent-core" || { echo "[vigent-serve] cd 실패: $ROOT/vigent-core (경로/TCC 확인)"; exit 1; }
echo "[vigent-serve] $(date '+%Y-%m-%d %H:%M:%S') cwd=$(pwd) host=${VIGENT_HOST} port=${PORT}"
exec "$PY" -m uvicorn main:app --host "${VIGENT_HOST}" --port ${PORT}
