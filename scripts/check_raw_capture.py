#!/usr/bin/env python3
"""[현장 검증] 촬영 폴더에 **주석 없는 원본이 실제로 있는지** 확인한다.

★왜 있는가 (2026-08-29)
  1차 방문 절차서에는 "녹화 회수(필수)"라고 적혀 있었다. 그런데 원본을 **만드는 장치도,
  있는지 확인하는 장치도** 없었다. 그 결과 929프레임을 찍고도 주석 없는 원본이 한 장도
  남지 않아 정답지를 만들 수 없게 됐다 — 재방문 외에 방법이 없어졌다.
  **적어 두는 것과 만드는 것은 다르다.** 그래서 절차를 스크립트로 만든다.

  이 스크립트는 CLAUDE.md 규칙 11의 실행판이다:
  "완료를 말하기 전에 결과물의 존재를 확인한다."

사용:
    python scripts/check_raw_capture.py runs/field_20260901
    python scripts/check_raw_capture.py D:/vigent_field/20260901   # 이관 후에도 같다

★통과할 때까지 현장을 떠나지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MIN_MB = 0.05          # 이보다 작으면 사실상 빈 파일로 본다


def check_scene(d: Path) -> list[str]:
    """장면 폴더 하나를 검사해 문제 목록을 돌려준다(빈 목록 = 통과)."""
    bad: list[str] = []
    raw = d / "original.mp4"
    ov = d / "overlay.mp4"
    dets = d / "dets.jsonl"

    if not raw.exists():
        bad.append("★original.mp4 가 없다 — 라벨링·재학습 재료가 통째로 없다")
    elif raw.stat().st_size < MIN_MB * 1e6:
        bad.append(f"★original.mp4 가 비어 있다({raw.stat().st_size} B)")
    if not ov.exists():
        bad.append("overlay.mp4 가 없다(부산물이지만 눈으로 볼 것이 없어진다)")
    if not dets.exists() or not dets.stat().st_size:
        bad.append("dets.jsonl 이 없거나 비어 있다")

    raw_stills = sorted((d / "raw").glob("still_*.jpg")) if (d / "raw").is_dir() else []
    ov_stills = sorted(d.glob("still_*.jpg"))
    if not raw_stills:
        bad.append("★raw/ 에 주석 없는 스틸이 하나도 없다")
    elif len(raw_stills) != len(ov_stills):
        bad.append(f"스틸 개수 불일치 — 원본 {len(raw_stills)} vs 오버레이 {len(ov_stills)}")

    # 원본 영상이 실제로 열리고 프레임이 나오는지 — 파일 크기만으로는 알 수 없다
    if raw.exists() and raw.stat().st_size >= MIN_MB * 1e6:
        try:
            import cv2
            cap = cv2.VideoCapture(str(raw))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            ok, _ = cap.read()
            cap.release()
            if not ok or n <= 0:
                bad.append(f"★original.mp4 를 열 수 없거나 프레임이 없다(frame_count={n})")
        except Exception as ex:  # noqa: BLE001
            bad.append(f"original.mp4 검사 실패: {type(ex).__name__}")

    # 라인 수(참고): dets 행 수와 원본 프레임 수가 크게 어긋나면 표시
    if dets.exists() and raw.exists():
        try:
            import cv2
            nl = sum(1 for x in dets.read_text(encoding="utf-8").splitlines() if x.strip())
            cap = cv2.VideoCapture(str(raw))
            nf = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if nf and abs(nl - nf) > max(3, nl * 0.05):
                bad.append(f"⚠dets {nl}행 vs 원본 {nf}프레임 — 어긋남(원인 확인 필요)")
        except Exception:  # noqa: BLE001
            pass
    return bad


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"❌ 폴더 없음: {root}")
        return 2

    scenes = sorted(p for p in root.iterdir()
                    if p.is_dir() and p.name != "raw" and (p / "dets.jsonl").exists())
    if not scenes:
        # ★규칙 11: 대상이 0개면 통과가 아니라 "검사하지 못함"이다
        print(f"❌ 검사할 장면이 없다: {root}")
        print("   (dets.jsonl 이 있는 하위 폴더를 장면으로 본다. 경로를 확인하라.)")
        return 1

    fails = 0
    print(f"■ 촬영 검증 — {root}  · 장면 {len(scenes)}개\n")
    for d in scenes:
        bad = check_scene(d)
        if bad:
            fails += 1
            print(f"  ❌ {d.name}")
            for b in bad:
                print(f"       · {b}")
        else:
            raw = d / "original.mp4"
            ns = len(list((d / "raw").glob("still_*.jpg")))
            print(f"  ✅ {d.name:<30} original.mp4 {raw.stat().st_size / 1e6:>6.1f}MB · 원본 스틸 {ns}장")
    print()
    if fails:
        print(f"★{fails}/{len(scenes)} 장면 실패 — **해당 장면은 다시 찍어야 한다.**")
        print("  현장을 떠나기 전에 재촬영하라. 돌아온 뒤에는 되돌릴 수 없다.")
        return 1
    print(f"★전 장면 통과 ({len(scenes)}개) — 주석 없는 원본이 모두 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
