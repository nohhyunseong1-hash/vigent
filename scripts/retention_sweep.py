#!/usr/bin/env python3
"""[Z-2] 디스크 보존 정책 스위퍼 — CLI. 라이브 서버와 완전히 분리된 별도 프로세스로 실행한다
(cron·작업 스케줄러에 얹는 것을 전제). guard.detect()의 DETECT_LOCK을 잡지 않고 GPU·모델을
전혀 건드리지 않아 실시간 검출과 무관하다 — 이 스크립트 실행이 오래 걸려도 라이브 검출은
지연되지 않는다(설계상 분리이지, 이 스크립트 자체의 소요시간은 --verbose로 실측 가능).

기본은 항상 안전한 쪽(dry-run, config 미설정 시 삭제 없음) — `config/tuning.yaml`의
`retention.enabled: true`로 켜고, `--execute`를 명시로 줘야 실제로 지운다.

사용:
  python scripts/retention_sweep.py                # 가시성만(스캔·크기 보고, 삭제 없음)
  python scripts/retention_sweep.py --execute       # retention.enabled=true 인 경우에만 실삭제
  python scripts/retention_sweep.py --group evidence --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import retention  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true",
                     help="실제 삭제(retention.enabled=true 일 때만 적용됨)")
    ap.add_argument("--group", default=None, help="특정 그룹만(예: evidence)")
    args = ap.parse_args()

    result = retention.sweep(execute=args.execute if args.execute else None, only_group=args.group)

    print(f"enabled={result['enabled']} dry_run={result['dry_run']} "
          f"executed_delete={result['executed_delete']} elapsed={result['elapsed_sec']}s")
    if result.get("disk_free_bytes") is not None:
        print(f"디스크 여유공간: {result['disk_free_bytes'] / 1024**3:.2f}GB")
    for w in result.get("warnings", []):
        print(f"⚠ {w}")
    print()
    for name, g in result["groups"].items():
        if not g.get("exists", True):
            print(f"[{name}] 디렉터리 없음")
            continue
        n_cand = len(g.get("candidates", []))
        n_del = len(g.get("deleted", []))
        print(f"[{name}] {g['dir']}: {g['file_count']}개 파일, {g['total_bytes']/1024:.1f}KB, "
              f"days={g['days']}, 최고령={g['oldest_age_days']}일, "
              f"삭제후보={n_cand}건" + (f", 실제삭제={n_del}건" if n_del else ""))

    print(f"\n상태 파일: {retention.STATUS_PATH.relative_to(_ROOT)}")
    if result.get("groups"):
        # 상세(파일별) 목록은 status.json에 이미 있음 — 콘솔은 요약만
        pass


if __name__ == "__main__":
    main()
