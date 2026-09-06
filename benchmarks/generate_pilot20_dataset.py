#!/usr/bin/env python3
"""[N] 파일럿 20장 검수용 데이터셋 생성.

data/field_eval/frames + labels_draft(conf 없음)를 그대로 쓰지 않고, 20장만 골라 편집용/참고용을
분리한 별도 폴더를 만든다:
  data/field_eval/pilot20/images/   20장 이미지(원본 복사)
  data/field_eval/pilot20/labels/   운용 임계 이상 박스만(YOLO txt, labelImg 편집 대상)
  data/field_eval/pilot20/hints/    참고용 미리보기(임계 이상=진한 실선, 0.10~임계=회색 점선, conf 표기)
  data/field_eval/pilot20/classes.txt

원본 data/field_eval/labels_draft/는 건드리지 않는다(정답지 출처 추적용, docs/labeling_guide.md §3-4).
conf는 labels_draft/*.txt에 없어 재검출이 필요(phase2_0_reverify.md §1-1과 동일한 이유) —
generate_prelabels_draft.py와 동일 조건(conf=0.10, imgsz=640, detectors=[person,ppe])으로 재현한다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
import tuning  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

DRAFT_CONF = 0.10
IMGSZ = 640
DETECTORS = ["person", "ppe"]

FRAMES_DIR = media("field_eval") / "frames"
CLASSES_PATH = media("field_eval") / "classes.txt"
_FE = media("field_eval")
OUT_DIR = _FE / "pilot20"  # 하위호환(기본값). --set 으로 바꾼다.

PILOT_20 = [
    "KakaoTalk_20260807_000633827_3000ms.jpg", "KakaoTalk_20260807_000552920_0ms.jpg",
    "KakaoTalk_20260807_000601541_8000ms.jpg", "KakaoTalk_20260807_000442974_1000ms.jpg",
    "KakaoTalk_20260807_000552920_11000ms.jpg", "KakaoTalk_20260807_000438282_1000ms.jpg",
    "KakaoTalk_20260807_000611749_1000ms.jpg", "KakaoTalk_20260807_000611749_0ms.jpg",
    "KakaoTalk_20260807_000633827_4000ms.jpg", "KakaoTalk_20260807_000611749_5000ms.jpg",
    "KakaoTalk_20260807_000442974_6000ms.jpg", "KakaoTalk_20260807_000552920_6000ms.jpg",
    "KakaoTalk_20260807_000601541_7000ms.jpg", "KakaoTalk_20260807_000632301_0ms.jpg",
    "KakaoTalk_20260807_000658251_1000ms.jpg", "KakaoTalk_20260807_000552920_19000ms.jpg",
    "KakaoTalk_20260807_000601541_2000ms.jpg", "KakaoTalk_20260807_000611749_13000ms.jpg",
    "KakaoTalk_20260807_000632301_8000ms.jpg", "KakaoTalk_20260807_000721865_16000ms.jpg",
]

_COLOR_ABOVE = {  # BGR, 진한 색(임계 이상 — 편집 대상)
    "person": (255, 140, 0), "Hardhat": (0, 170, 0), "NO-Hardhat": (0, 0, 220),
    "Safety-Vest": (0, 170, 0), "NO-Safety-Vest": (0, 0, 220),
    "Mask": (0, 170, 0), "NO-Mask": (0, 0, 220),
}
_COLOR_BELOW = (150, 150, 150)  # 회색(0.10~임계 — 참고용 점선)


def _op_thresh(cls: str, op_thresh: dict[str, float]) -> float:
    return op_thresh["person"] if cls == "person" else op_thresh["ppe"]


def _draw_dashed_rect(img, pt1, pt2, color, thickness=2, dash=8) -> None:
    x1, y1 = pt1
    x2, y2 = pt2
    for x in range(x1, x2, dash * 2):
        cv2.line(img, (x, y1), (min(x + dash, x2), y1), color, thickness)
        cv2.line(img, (x, y2), (min(x + dash, x2), y2), color, thickness)
    for y in range(y1, y2, dash * 2):
        cv2.line(img, (x1, y), (x1, min(y + dash, y2)), color, thickness)
        cv2.line(img, (x2, y), (x2, min(y + dash, y2)), color, thickness)


def _guard_overwrite(labels_dir: Path, force: bool) -> None:
    """★검수 완료본 보호(규칙2·6): 이미 라벨이 있는 폴더를 초안으로 덮어쓰지 않는다.

    pilot20/labels/ 는 2026-08-07 검수 완료본(93건)이다 — 이 스크립트를 무심코 재실행해서
    사람이 검수한 결과를 모델 초안으로 되돌리는 사고를 막는다.
    """
    if force or not labels_dir.exists():
        return
    existing = [p for p in labels_dir.glob("*.txt") if p.name != "classes.txt"]
    n_boxes = sum(len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]) for p in existing)
    if existing:
        raise SystemExit(
            f"★중단: {labels_dir} 에 이미 라벨 {len(existing)}개 파일(박스 {n_boxes}건)이 있다.\n"
            "  이 스크립트는 '모델 초안'을 쓰므로, 사람이 검수한 결과를 덮어쓸 수 있다.\n"
            "  정말 초안으로 되돌리려면 --force 를 붙이되, 먼저 폴더를 백업할 것.\n"
            "  (검수본 회수는 benchmarks/cvat_setup_pilot.py export 를 쓴다.)"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="검수용 데이터셋 생성(임계 이상 labels/ + 참고용 hints/)")
    ap.add_argument("--set", dest="which", choices=["pilot20", "rest89"], default="pilot20",
                    help="pilot20=파일럿 20장(기본) / rest89=나머지 89장")
    ap.add_argument("--force", action="store_true", help="기존 labels/ 를 덮어쓴다(위험 — 백업 후에만)")
    args = ap.parse_args()

    global OUT_DIR
    if args.which == "rest89":
        OUT_DIR = _FE / "rest89"
        targets = sorted(p.name for p in FRAMES_DIR.glob("*.jpg") if p.name not in set(PILOT_20))
        if len(targets) != 89:
            print(f"  [주의] 대상이 89장이 아니라 {len(targets)}장이다(frames/ 내용 확인 필요)")
    else:
        targets = list(PILOT_20)
    print(f"대상 세트: {args.which} ({len(targets)}장) → {OUT_DIR}")

    classes = [c.strip() for c in CLASSES_PATH.read_text(encoding="utf-8").splitlines() if c.strip()]
    class_ids = {c: i for i, c in enumerate(classes)}
    _guard_overwrite(OUT_DIR / "labels", args.force)

    conf_cfg = tuning.section("detect").get("conf") or {}
    op_thresh = {"person": float(conf_cfg.get("person", 0.35)), "ppe": float(conf_cfg.get("ppe", 0.35))}
    print(f"운용 임계(실측): person={op_thresh['person']} ppe={op_thresh['ppe']}")

    images_dir = OUT_DIR / "images"
    labels_dir = OUT_DIR / "labels"
    hints_dir = OUT_DIR / "hints"
    for d in (images_dir, labels_dir, hints_dir):
        d.mkdir(parents=True, exist_ok=True)

    (labels_dir / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    (OUT_DIR / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")

    guard = bq._build_guard()

    stats: list[dict[str, Any]] = []
    for fname in targets:
        src = FRAMES_DIR / fname
        if not src.exists():
            raise SystemExit(f"[generate_pilot20_dataset] 프레임 없음: {src}")
        img = cv2.imread(str(src))
        stem = src.stem

        shutil.copy2(src, images_dir / fname)

        out = detect_isolated(guard, img, detectors=DETECTORS, conf=DRAFT_CONF, imgsz=IMGSZ)
        dets = [d for d in out.get("detections", []) if d.get("label") in class_ids]

        above = [d for d in dets if float(d.get("conf", 0.0)) >= _op_thresh(d["label"], op_thresh)]
        below = [d for d in dets if float(d.get("conf", 0.0)) < _op_thresh(d["label"], op_thresh)]

        lines = []
        for d in above:
            x1, y1, x2, y2 = d["bbox"]
            cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
            lines.append(f"{class_ids[d['label']]} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        (labels_dir / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        hint_img = img.copy()
        ih, iw = hint_img.shape[:2]
        for d in below:
            x1, y1, x2, y2 = d["bbox"]
            p1, p2 = (int(x1 * iw), int(y1 * ih)), (int(x2 * iw), int(y2 * ih))
            _draw_dashed_rect(hint_img, p1, p2, _COLOR_BELOW, thickness=1)
            cv2.putText(hint_img, f"{d['label']} {d['conf']:.2f}", (p1[0], max(0, p1[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, _COLOR_BELOW, 1, cv2.LINE_AA)
        for d in above:
            x1, y1, x2, y2 = d["bbox"]
            p1, p2 = (int(x1 * iw), int(y1 * ih)), (int(x2 * iw), int(y2 * ih))
            color = _COLOR_ABOVE.get(d["label"], (255, 255, 255))
            cv2.rectangle(hint_img, p1, p2, color, 2)
            cv2.putText(hint_img, f"{d['label']} {d['conf']:.2f}", (p1[0], max(0, p1[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)
        cv2.imwrite(str(hints_dir / f"{stem}.jpg"), hint_img)

        stats.append({"file": fname, "above": len(above), "below": len(below)})
        print(f"  {fname}: 임계이상 {len(above)}건(labels/에 기록) · 0.10~임계 {len(below)}건(hints/에만 회색 표기)")

    total_above = sum(s["above"] for s in stats)
    total_below = sum(s["below"] for s in stats)
    print(f"\n총 {len(targets)}장 — 임계 이상(편집 대상) {total_above}건 · 0.10~임계(참고용) {total_below}건")
    print(f"출력: {OUT_DIR}")


if __name__ == "__main__":
    main()
