#!/bin/bash
# VIGENT /health 워치독 (C-S1). /health 가 N회 연속 실패하면 서비스 재기동.
#   - systemd: vigent-watchdog.timer 가 주기 실행 → 실패 시 systemctl restart
#   - macOS/cron: 이 스크립트를 주기 실행(launchd StartInterval 또는 crontab)
# 환경변수:
#   VIGENT_HEALTH_URL  (기본 http://127.0.0.1:8010/health)
#   VIGENT_API_TOKEN   (설정 시 Bearer 로 인증 — 토큰 배포 환경)
#   VIGENT_RESTART_CMD (기본 systemctl restart vigent-edge / 미설정 시 재기동 생략하고 경고만)
#   VIGENT_HEALTH_FAILS (연속 실패 임계, 기본 3)
set -u
URL="${VIGENT_HEALTH_URL:-http://127.0.0.1:8010/health}"
FAILS="${VIGENT_HEALTH_FAILS:-3}"
AUTH=()
[ -n "${VIGENT_API_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${VIGENT_API_TOKEN}")

# ★[CODE_AUDIT_20260928 #4] 재기동 직후 유예 — /health 는 예열(phase=starting) 중 503 을 준다. 재기동 30 s 뒤 점검이 다시 503 을 보면
#   무한 재기동 루프가 됐다. (1) 예열 중(본문 phase=starting)이면 정상으로 본다 (2) 마지막 재기동 뒤 GRACE_S 안에는 재기동하지 않는다.
GRACE_S="${VIGENT_RESTART_GRACE_S:-120}"
STATE="${VIGENT_WATCHDOG_STATE:-/tmp/vigent_watchdog_last_restart}"
BODY_TMP="$(mktemp 2>/dev/null || echo /tmp/vigent_watchdog_body.$$)"
ok=0; starting=0
for i in $(seq 1 "$FAILS"); do
  code=$(curl -s -o "$BODY_TMP" -w "%{http_code}" --max-time 5 ${AUTH[@]+"${AUTH[@]}"} "$URL" 2>/dev/null)
  if [ "$code" = "200" ]; then ok=1; break; fi
  if grep -q '"phase"[[:space:]]*:[[:space:]]*"starting"' "$BODY_TMP" 2>/dev/null; then starting=1; break; fi
  sleep 2
done
rm -f "$BODY_TMP"
if [ "$starting" = "1" ]; then
  echo "[watchdog] 예열 중(phase=starting) — 재기동하지 않음"
  exit 0
fi
if [ -f "$STATE" ]; then
  last=$(cat "$STATE" 2>/dev/null || echo 0); now=$(date +%s)
  if [ $((now - last)) -lt "$GRACE_S" ] && [ "$ok" != "1" ]; then
    echo "[watchdog] 마지막 재기동 $((now - last))s 전 — 유예 ${GRACE_S}s 안이라 재기동하지 않음"
    exit 0
  fi
fi

STATUS_URL="${VIGENT_STATUS_URL:-http://127.0.0.1:8010/status}"
HANG_RESTART_S="${VIGENT_HANG_RESTART_S:-45}"   # 앱 내부 hang 복구(15s)보다 충분히 커서 계층 안 겹침
if [ "$ok" = "1" ]; then
  # 2차 방어(hang): 프로세스 생존·/health OK 여도 워커가 HANG_RESTART_S 이상 정지 지속이면 재기동
  #   (1차=앱 내부 자동 재기동 VIGENT_HANG_TIMEOUT. 그게 실패해 hang 이 오래 남을 때만 프로세스 재기동)
  hung=$(curl -s --max-time 5 ${AUTH[@]+"${AUTH[@]}"} "$STATUS_URL" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin); cams = d.get('cameras', {})
    idles = [c.get('last_frame_secs_ago') or 0 for c in cams.values() if c.get('running')]
    m = max(idles) if idles else 0
    print('HANG' if (d.get('any_hang') and m > $HANG_RESTART_S) else 'OK')
except Exception:
    print('OK')
" 2>/dev/null)
  if [ "$hung" != "HANG" ]; then
    echo "[watchdog] OK ($URL)"
    exit 0
  fi
  echo "[watchdog] ⚠️ 워커 HANG 지속(>${HANG_RESTART_S}s) — 앱 내부 복구 실패 → 프로세스 재기동(2차 방어)"
fi

echo "[watchdog] 비정상 — /health $FAILS회 연속 실패 ($URL)"
date +%s > "$STATE" 2>/dev/null || true
if [ -n "${VIGENT_RESTART_CMD:-}" ]; then
  echo "[watchdog] 재기동: $VIGENT_RESTART_CMD"
  eval "$VIGENT_RESTART_CMD"
elif command -v systemctl >/dev/null 2>&1; then
  echo "[watchdog] 재기동: systemctl restart vigent-edge"
  systemctl restart vigent-edge
else
  echo "[watchdog] ⚠️ 재기동 명령 없음(VIGENT_RESTART_CMD 미설정, systemd 아님). 수동 확인 필요."
  exit 1
fi
