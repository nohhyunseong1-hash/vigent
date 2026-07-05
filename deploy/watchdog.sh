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

ok=0
for i in $(seq 1 "$FAILS"); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${AUTH[@]}" "$URL" 2>/dev/null)
  if [ "$code" = "200" ]; then ok=1; break; fi
  sleep 2
done

if [ "$ok" = "1" ]; then
  echo "[watchdog] OK ($URL)"
  exit 0
fi

echo "[watchdog] 비정상 — /health $FAILS회 연속 실패 ($URL)"
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
