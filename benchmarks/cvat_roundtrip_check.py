#!/usr/bin/env python3
"""[N-3] CVAT 왕복 테스트 — import 전 원본과 export 결과를 파일 단위로 비교한다.

사용법:
  python3 benchmarks/cvat_roundtrip_check.py <원본_labels_dir> <export된_labels_dir> <classes.txt>

완전 동일해야 통과(사용자 지시) — 박스 개수·클래스·좌표(정규화 0~1) 전부. 좌표는 부동소수점이라
1e-4(≈0.01% — 1000px 기준 0.1px 미만) 이내 차이는 "동일"로 본다(라운드트립 시 텍스트 직렬화
자릿수 손실만 허용, 실제 편집으로 인한 변화는 이보다 훨씬 큼). 파일별로 박스를 (class_id, cx, cy, w, h)
집합으로 놓고 순서 무관 비교(CVAT가 export 시 박스 순서를 바꿀 수 있음 — 순서는 채점에 무관하므로
순서 불일치는 실패로 치지 않는다, 내용만 같으면 통과).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EPS = 1e-4


def _read_yolo(path: Path) -> list[tuple[int, float, float, float, float]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cid = int(parts[0])
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append((cid, cx, cy, w, h))
    return out


def _match(a: tuple, b: tuple) -> bool:
    if a[0] != b[0]:
        return False
    return all(abs(a[i] - b[i]) <= EPS for i in range(1, 5))


def _boxes_equal(before: list[tuple], after: list[tuple]) -> bool:
    if len(before) != len(after):
        return False
    remaining = list(after)
    for b in before:
        hit = next((r for r in remaining if _match(b, r)), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return True


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("사용법: cvat_roundtrip_check.py <원본_dir> <export_dir> <classes.txt>")
    before_dir, after_dir = Path(sys.argv[1]), Path(sys.argv[2])
    classes = [c.strip() for c in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if c.strip()]
    print(f"클래스 스킴({len(classes)}개): {classes}")

    before_files = sorted(p.name for p in before_dir.glob("*.txt") if p.name != "classes.txt")
    after_files = sorted(p.name for p in after_dir.glob("*.txt") if p.name != "classes.txt")

    if before_files != after_files:
        only_before = set(before_files) - set(after_files)
        only_after = set(after_files) - set(before_files)
        print(f"★파일 목록 자체가 다름 — before전용 {sorted(only_before)} / after전용 {sorted(only_after)}")

    all_names = sorted(set(before_files) | set(after_files))
    match_count = 0
    mismatches: list[str] = []
    for name in all_names:
        b = _read_yolo(before_dir / name)
        a = _read_yolo(after_dir / name)
        if _boxes_equal(b, a):
            match_count += 1
        else:
            mismatches.append(name)
            print(f"  [불일치] {name}: before={len(b)}건 after={len(a)}건")
            print(f"    before={b}")
            print(f"    after ={a}")

    total = len(all_names)
    print(f"\n=== 결과: {match_count}/{total} 파일 완전 일치 ===")
    if mismatches:
        print(f"불일치 파일({len(mismatches)}개): {mismatches}")
        raise SystemExit(1)
    print("전부 일치 — 왕복 테스트 통과.")


if __name__ == "__main__":
    main()
