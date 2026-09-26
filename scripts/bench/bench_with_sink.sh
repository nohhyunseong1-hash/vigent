#!/bin/bash
# scripts/bench/bench_with_sink.sh — 저장소(.venv) 서버로 4채널 벤치를 "로컬 싱크만" 조건으로 돌리는 한 줄 실행기. [2026-09-26]
#
# 하는 일: config/notify.yaml 백업 → 싱크 전용(웹훅 127.0.0.1:9911, 실채널 없음)으로 교체 → local_sink 기동 → bench_4ch.py 실행 →
#          어떤 경우에도(Ctrl+C 포함) notify.yaml 원복 + 싱크 종료. 실채널 서버를 개발기에 남기지 않는다(CLAUDE.md 운용 원칙).
# 사용:   bash scripts/bench/bench_with_sink.sh <tag> <minutes> [theme] [extra bench args...]
#   예:   bash scripts/bench/bench_with_sink.sh fk2_academy_torch 30 academy_fk2_tmp --detect-backend torch
# ★벤치 자체의 가드(실채널·GPU 오염·포트)는 그대로다 — GPU 를 500MB 이상 쓰는 다른 앱(예: msw.exe)이 있으면 시작하지 않는다.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${1:?tag}"; MIN="${2:-30}"; THEME="${3:-safety}"; shift 3 2>/dev/null || shift $#
PY="$ROOT/.venv/Scripts/python.exe"
NOTIFY="$ROOT/config/notify.yaml"; BAK="$ROOT/config/notify.yaml.bak_bench_$$"
SINK_PID=""
restore() {
  [ -f "$BAK" ] && { cp -f "$BAK" "$NOTIFY"; rm -f "$BAK"; echo "[bench_with_sink] notify.yaml 원복"; }
  [ -n "$SINK_PID" ] && { taskkill //PID "$SINK_PID" //F > /dev/null 2>&1 || kill "$SINK_PID" 2>/dev/null; echo "[bench_with_sink] local sink 종료"; }
}
trap restore EXIT INT TERM
cp -f "$NOTIFY" "$BAK"
printf "telegram_chat: ''\nwebhook_url: 'http://127.0.0.1:9911/sink'\nsmtp_host: ''\nsmtp_port: '587'\nsmtp_user: ''\nemail_to: ''\ntelegram_token: ''\n" > "$NOTIFY"
echo "[bench_with_sink] notify.yaml → 싱크 전용(백업 $(basename "$BAK"))"
PYTHONIOENCODING=utf-8 "$PY" "$ROOT/scripts/bench/local_sink.py" --port 9911 --out "$ROOT/audit/bench_sink_${TAG}.jsonl" > /dev/null 2>&1 &
SINK_PID=$!; sleep 2
echo "[bench_with_sink] sink pid $SINK_PID · theme $THEME · $MIN 분 · tag $TAG"
VIGENT_THEME="$THEME" VIGENT_INCLUDE_FORKLIFT="${VIGENT_INCLUDE_FORKLIFT:-1}" PYTHONIOENCODING=utf-8 \
  "$PY" "$ROOT/scripts/bench/bench_4ch.py" --tag "$TAG" --minutes "$MIN" "$@"
rc=$?
echo "[bench_with_sink] bench exit=$rc"
exit $rc
