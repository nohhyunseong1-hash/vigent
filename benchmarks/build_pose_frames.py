"""build_pose_frames.py — 포즈 패리티용 고정 샘플 프레임셋 구성 (T10c Stage 0).

사람이 포함된 기존 자산에서 ~30장을 '결정적으로' 골라 benchmarks/data/pose_frames/ 에 고정한다.
(무작위 없음 — 정렬 + 고정 stride/인덱스 → 재현 가능). 클립 회귀셋은 사용자 촬영본 도착 시 별도 추가.

소스:
  · data/evidence 의 fall/ergonomic JPG(대상 자세) + ppe_missing/zone_intrusion JPG(직립·작업 자세)
  · runs/ 렌더 영상에서 고정 인덱스 프레임 추출(보행·모션)
실행: /opt/anaconda3/bin/python3 benchmarks/build_pose_frames.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "benchmarks" / "data" / "pose_frames"


def _evidence_jpgs() -> list[Path]:
    ev = _ROOT / "data" / "evidence"
    fall_ergo = sorted(p for p in ev.rglob("*.jpg")
                       if ("fall" in p.name.lower() or "ergonomic" in p.name.lower()))
    people = sorted(p for p in ev.rglob("*.jpg")
                    if any(k in p.name.lower() for k in ("ppe_missing", "zone_intrusion", "proximity", "crowd")))
    # 직립/작업 자세 15장: 정렬 후 균등 stride(결정적)
    picked = people[:: max(1, len(people) // 15)][:15] if people else []
    return fall_ergo + picked   # 대상 자세(3) + 직립(15)


def _video_frames() -> list[tuple[str, Path, list[int]]]:
    return [
        ("walk", _ROOT / "runs" / "rfdetr" / "test_walk.mp4", [0, 6, 12, 18, 24, 30, 36, 42]),
        ("pipe", _ROOT / "runs" / "safety" / "pipeline_out.mp4", [0, 12, 24, 36]),
    ]


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    for old in _OUT.glob("*.jpg"):
        old.unlink()   # 재실행 시 깨끗이(결정적 재구성)
    n = 0
    for i, src in enumerate(_evidence_jpgs()):
        dst = _OUT / f"ev_{i:02d}_{src.name}"
        shutil.copyfile(src, dst)
        n += 1
    for tag, vpath, idxs in _video_frames():
        if not vpath.exists():
            continue
        cap = cv2.VideoCapture(str(vpath))
        for fi in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if ok:
                cv2.imwrite(str(_OUT / f"vid_{tag}_{fi:03d}.jpg"), frame)
                n += 1
        cap.release()
    print(f"고정 프레임셋 구성: {n}장 → {_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
