#!/bin/bash
# T10b 학습 진행 뷰어. 사용법:
#   ! bash training/watch_progress.sh            (1회 출력)
#   ! bash training/watch_progress.sh watch      (15초마다 자동 새로고침, Ctrl-C 종료)
LOG="${TRAIN_LOG:-/Users/nohyeonseong/.claude/jobs/45405339/tmp/train_forklift.log}"
OUT="${TRAIN_OUT:-$HOME/Downloads/rfdetr_forklift}"
TOTAL_EPOCHS="${TOTAL_EPOCHS:-50}"
CLASS="${TRAIN_CLASS:-forklift}"

render() {
  [ -f "$LOG" ] || { echo "로그 없음: $LOG"; return; }
  local start now el done_ep rate eta_s best running ck
  start=$(grep -aoE "\[2026-[0-9: -]+\]" "$LOG" | head -1 | tr -d '[]')
  done_ep=$(( $(grep -acE "AP 50:95" "$LOG") / 2 ))
  [ "$done_ep" -lt 1 ] && done_ep=0
  best=$(grep -aoE "improved to [0-9.]+ \(epoch [0-9]+\)" "$LOG" | tail -1)
  if pgrep -f rfdetr_train.py >/dev/null 2>&1; then running="🟢 학습 중"; else
    grep -qa TRAIN_DONE "$LOG" && running="✅ 완료" || running="🔴 중단(로그 확인)"; fi
  # 경과·ETA(로그 첫 타임스탬프 ~ 지금)
  el=$(( $(date +%s) - $(date -j -f "%Y-%m-%d %H:%M:%S" "$start" +%s 2>/dev/null || echo $(date +%s)) ))
  local pct=$(( done_ep * 100 / TOTAL_EPOCHS ))
  local bar_n=$(( pct / 5 )); local bar=""
  for ((i=0;i<20;i++)); do [ $i -lt $bar_n ] && bar+="█" || bar+="░"; done
  echo "════════ VIGENT T10b 학습 진행 [$CLASS] ════════"
  echo "  상태: $running"
  echo "  진행: [$bar] ${pct}%  (${done_ep}/${TOTAL_EPOCHS} epoch)"
  if [ "$done_ep" -ge 1 ] && [ "$el" -gt 0 ]; then
    rate=$(( el / done_ep ))
    eta_s=$(( (TOTAL_EPOCHS - done_ep) * rate ))
    echo "  경과: $((el/60))분  ·  epoch당 ~${rate}초  ·  남은시간 ~$((eta_s/60))분"
    echo "  예상완료: $(date -v +${eta_s}S "+%H:%M" 2>/dev/null)"
  fi
  echo "  최신 best: ${best:-(아직 없음)}"
  ck=$(ls -t "$OUT"/*.pth 2>/dev/null | head -1)
  echo "  최신 체크포인트: ${ck:-(없음)}"
  echo "════════════════════════════════════════════════"
}

if [ "$1" = "watch" ]; then
  while true; do clear; render; echo "  (15초마다 새로고침 · Ctrl-C 종료)"; \
    pgrep -f rfdetr_train.py >/dev/null 2>&1 || { echo "  학습 종료됨."; break; }; sleep 15; done
else
  render
fi
