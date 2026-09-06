#!/usr/bin/env python3
"""[Q] 검수 완료본 통합 — pilot20/labels + rest89/labels → data/field_eval/labels/

측정 하네스가 읽는 최종 경로(`docs/labeling_guide.md` §4 폴더 구조)로 정답지를 모은다.
labels_draft/ 는 건드리지 않는다(정답지 출처 추적용, §3-4).

사용법:
  python benchmarks/assemble_field_eval_labels.py          # 통합 + 검증
  python benchmarks/assemble_field_eval_labels.py --force  # 기존 labels/ 를 덮어씀(백업은 자동)

검증 항목(하나라도 어긋나면 비정상 종료):
  1) 파일 수 109개 · frames/ 의 .jpg 목록과 basename 이 정확히 일치
  2) 두 소스 사이에 파일명 중복이 없음
  3) 클래스 id 가 0~6 범위
  4) 통합 전후 박스 총합이 보존됨

좌표 정리(clip): 화면 가장자리에 걸친 객체는 박스가 이미지 밖으로 미세하게 넘칠 수 있다
(모델 초안 좌표 + CVAT 왕복에서 발생, 2026-08-08 실측 49건/최대 1.1%). 이런 박스는
0~1 범위로 잘라 넣고 몇 건을 얼마나 잘랐는지 출력한다. **소스 폴더(pilot20/rest89)는
수정하지 않는다** — 통합본에만 적용해 원본 추적성을 유지한다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)
_FE = media("field_eval")
_SOURCES = [_FE / "pilot20" / "labels", _FE / "rest89" / "labels"]
_FRAMES = _FE / "frames"
_OUT = _FE / "labels"
_CLASSES = _FE / "classes.txt"


def _boxes(path: Path) -> list[tuple[int, float, float, float, float]]:
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        a = ln.split()
        out.append((int(a[0]), *(float(x) for x in a[1:5])))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="검수 완료 라벨 통합")
    ap.add_argument("--force", action="store_true", help="기존 labels/ 가 있어도 진행(자동 백업 후 덮어씀)")
    args = ap.parse_args()

    classes = [c.strip() for c in _CLASSES.read_text(encoding="utf-8").splitlines() if c.strip()]
    for src in _SOURCES:
        if not src.exists():
            raise SystemExit(f"소스 폴더 없음: {src}")

    # 1) 수집 + 중복 검사
    collected: dict[str, Path] = {}
    for src in _SOURCES:
        n = 0
        for p in sorted(src.glob("*.txt")):
            if p.name == "classes.txt":
                continue
            if p.name in collected:
                raise SystemExit(f"★파일명 중복: {p.name} ({collected[p.name].parent} vs {src})")
            collected[p.name] = p
            n += 1
        print(f"  {src.relative_to(_ROOT)}: {n}개")

    # 2) frames/ 와 대조
    frame_stems = {p.stem for p in _FRAMES.glob("*.jpg")}
    got_stems = {Path(n).stem for n in collected}
    missing = sorted(frame_stems - got_stems)
    extra = sorted(got_stems - frame_stems)
    if missing or extra:
        raise SystemExit(f"★frames/ 와 불일치 — 누락 {len(missing)}개 {missing[:5]} / 초과 {len(extra)}개 {extra[:5]}")
    print(f"  frames/ 대조: {len(frame_stems)}장 전부 일치 ✔")

    # 3) 내용 검증 + 좌표 clip + 집계
    per_class: Counter[str] = Counter()
    total = 0
    empty = 0
    clipped = 0
    max_over = 0.0
    fixed: dict[str, list[str]] = {}
    for name, p in collected.items():
        bs = _boxes(p)
        if not bs:
            empty += 1
        lines: list[str] = []
        for cid, cx, cy, w, h in bs:
            if not (0 <= cid < len(classes)):
                raise SystemExit(f"★클래스 id 범위 벗어남: {name} cid={cid}")
            x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            over = max(0.0, -x1, -y1, x2 - 1.0, y2 - 1.0)
            if over > 1e-9:
                clipped += 1
                max_over = max(max_over, over)
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(1.0, x2), min(1.0, y2)
                cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
            lines.append(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
            per_class[classes[cid]] += 1
            total += 1
        fixed[name] = lines
    if clipped:
        print(f"  좌표 clip: {clipped}건을 0~1 로 잘라 넣음(최대 초과 {max_over * 100:.2f}% — 소스는 미수정)")

    # 4) 기존 labels/ 보호(규칙2)
    if _OUT.exists():
        existing = [p for p in _OUT.glob("*.txt") if p.name != "classes.txt"]
        if existing and not args.force:
            raise SystemExit(
                f"★중단: {_OUT} 에 이미 {len(existing)}개 파일이 있다.\n"
                "  덮어쓰려면 --force (자동 백업 후 진행)."
            )
        if existing:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup = _FE / f"labels_backup_{stamp}"
            shutil.copytree(_OUT, backup)
            print(f"  기존 labels/ 백업: {backup.name}")

    _OUT.mkdir(parents=True, exist_ok=True)
    for name in sorted(fixed):
        body = "\n".join(fixed[name])
        (_OUT / name).write_text(body + ("\n" if body else ""), encoding="utf-8")
    (_OUT / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")

    # 5) 통합 후 재검증(보존 확인)
    after_total = sum(len(_boxes(p)) for p in _OUT.glob("*.txt") if p.name != "classes.txt")
    after_files = len([p for p in _OUT.glob("*.txt") if p.name != "classes.txt"])
    print(f"\n  출력: {_OUT}")
    print(f"  파일 {after_files}개 · 박스 {after_total}건 · 빈 라벨 {empty}장")
    if after_total != total or after_files != len(collected):
        raise SystemExit(f"★통합 전후 불일치: 전 {total}건/{len(collected)}개 → 후 {after_total}건/{after_files}개")

    print("\n=== 클래스별 ===")
    for c in classes:
        print(f"  {c:<16}{per_class.get(c, 0)}")
    print(f"  {'합계':<16}{total}")
    print("\n✅ 통합 완료 — 검증 4종 전부 통과.")


if __name__ == "__main__":
    main()
