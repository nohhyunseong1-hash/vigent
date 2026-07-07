#!/usr/bin/env bash
# setup_worktree.sh — 새 git worktree에 .gitignore 대상 자산을 연결·검증한다(F-8 재발 방지).
#
# 배경: `git worktree add` 는 추적 파일만 체크아웃한다. weights/·data/·.env 는 .gitignore 라
#   워크트리에 빠지고, 그러면 서버가 커스텀 모델 대신 COCO 로 조용히 폴백해 검출이 무력화된다
#   (2026-07-07 F-8). 이 스크립트는 메인 워킹트리의 자산을 심링크로 연결하고 존재를 검증한다.
#
# 사용: 워크트리 루트에서
#   bash scripts/setup_worktree.sh [메인_워킹트리_경로]
#   (메인 경로 생략 시 기본값 사용)
set -euo pipefail

MAIN="${1:-/Users/nohyeonseong/Desktop/VIGENT}"
WT="$(pwd)"

if [ "$WT" = "$MAIN" ]; then
  echo "✗ 여기가 메인 워킹트리($MAIN)입니다. 워크트리 안에서 실행하세요." >&2
  exit 1
fi
if [ ! -d "$MAIN/vigent-core/weights" ]; then
  echo "✗ 메인 경로에 weights 가 없습니다: $MAIN/vigent-core/weights" >&2
  exit 1
fi

echo "== 워크트리 자산 연결: $WT (원본: $MAIN) =="

# 1) 가중치(런타임 필수 — 없으면 F-8 폴백)
ln -sfn "$MAIN/vigent-core/weights" "$WT/vigent-core/weights"

# 2) 평가·학습 데이터(벤치 필수). 있으면만 연결.
[ -d "$MAIN/data" ] && ln -sfn "$MAIN/data" "$WT/data" || true
[ -d "$MAIN/benchmarks/data" ] && ln -sfn "$MAIN/benchmarks/data" "$WT/benchmarks/data" || true

# 3) 비밀(.env) — 있으면 복사(심링크 아님: 워크트리별 격리 여지). 없으면 조용히 넘어감.
[ -f "$MAIN/.env" ] && cp -n "$MAIN/.env" "$WT/.env" 2>/dev/null || true

echo "== 검증 =="
fail=0
n_pth="$(ls -L "$WT/vigent-core/weights/"*.pth 2>/dev/null | wc -l | tr -d ' ')"
echo "  weights .pth: ${n_pth}개 $([ "$n_pth" -ge 1 ] && echo '✓' || { echo '✗'; fail=1; })"
echo "  data/: $([ -e "$WT/data/datasets" ] && echo '✓' || echo '(없음 — 벤치 시 필요)')"
echo "  benchmarks/data/: $([ -e "$WT/benchmarks/data/fire_smoke" ] && echo '✓' || echo '(없음 — 벤치 시 필요)')"

# 4) 서버 기동 시 커스텀 가중치 실로드를 보장(F-8): 부재면 기동 거부되므로, 여기서 미리 경고.
if [ "$fail" -ne 0 ]; then
  echo "✗ weights 누락 — 서버는 F-8 가드로 기동을 거부합니다(VIGENT_ALLOW_FALLBACK=1 로만 COCO 폴백)." >&2
  exit 1
fi
echo "✓ 자산 연결 완료. 이제 이 워크트리에서 서버·벤치를 실행해도 됩니다."
