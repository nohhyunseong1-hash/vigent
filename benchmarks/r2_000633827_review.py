#!/usr/bin/env python3
"""[R-2] 000633827 영상 재검토용 미리보기 생성 — GT 와 검출을 나란히(좌우) 배치.

P-2 하류 오탐 확인([Q-3] 이후 재확인 시에도)에서 "완전 유령" 미착용 경보 8건이 전부 이 영상
(KakaoTalk_20260807_000633827, 14프레임 전부 dev)에 몰려 있었다. 89장 검수 때도 이 영상만
유일하게 삭제(19)가 추가(2)를 압도했다(field_eval_gt_summary.md §3) — 정답지 오류인지 모델
특성인지 판정이 필요한 첫 대상(perf_improvement_plan.md P-3-3).

판정은 하지 않는다(사용자가 직접 본다) — 여기서는 GT(왼쪽, 정답지 data/field_eval/labels/)와
운영 경로 검출(오른쪽, person+ppe 앙상블, 운용 임계 person 0.40/ppe 0.35)을 나란히 그려
data/field_eval/review_000633827/ 에 저장만 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import field_eval  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

VIDEO = "KakaoTalk_20260807_000633827"
FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
OUT_DIR = field_eval("review_000633827")
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))

_COLOR = {
    "person": (255, 140, 0), "Hardhat": (0, 170, 0), "NO-Hardhat": (0, 0, 220),
    "Safety-Vest": (0, 170, 0), "NO-Safety-Vest": (0, 0, 220),
    "Mask": (0, 170, 0), "NO-Mask": (0, 0, 220),
}


def _load_gt(stem: str) -> list[dict[str, Any]]:
    txt = LABELS_DIR / f"{stem}.txt"
    out = []
    if not txt.exists():
        return out
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        cls = CLASSES[int(parts[0])]
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append({"label": cls, "bbox": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]})
    return out


def _draw(img: np.ndarray, boxes: list[dict[str, Any]], show_conf: bool) -> np.ndarray:
    vis = img.copy()
    h, w = vis.shape[:2]
    for d in boxes:
        x1, y1, x2, y2 = d["bbox"]
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        color = _COLOR.get(d["label"], (200, 200, 200))
        cv2.rectangle(vis, p1, p2, color, 2)
        label = d["label"]
        if show_conf and "conf" in d:
            label = f"{label} {d['conf']:.2f}"
        cv2.putText(vis, label, (p1[0], max(0, p1[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    return vis


def _label_bar(w: int, text: str) -> np.ndarray:
    bar = np.full((28, w, 3), 40, dtype=np.uint8)
    cv2.putText(bar, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return bar


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    guard = bq._build_guard()

    frames = sorted(
        (f for f in SPLIT["dev"] if f.startswith(VIDEO)),
        key=lambda f: int(f.split("_")[-1].replace("ms.jpg", "")),
    )
    print(f"{VIDEO}: dev {len(frames)}장 전부 재검토 대상")

    for fname in frames:
        stem = Path(fname).stem
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            print(f"  [경고] 이미지 로드 실패: {fname}")
            continue
        gt_boxes = _load_gt(stem)
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        det_boxes = out.get("detections", [])

        gt_vis = _draw(img, gt_boxes, show_conf=False)
        det_vis = _draw(img, det_boxes, show_conf=True)
        w = img.shape[1]
        gt_panel = np.vstack([_label_bar(w, f"GT(정답지) — 박스 {len(gt_boxes)}개"), gt_vis])
        det_panel = np.vstack([_label_bar(w, f"검출(운영경로: person+ppe 앙상블) — 박스 {len(det_boxes)}개"), det_vis])
        divider = np.full((gt_panel.shape[0], 4, 3), (255, 255, 255), dtype=np.uint8)
        combined = np.hstack([gt_panel, divider, det_panel])
        title = np.vstack([_label_bar(combined.shape[1], fname), combined])

        out_path = OUT_DIR / f"{stem}.jpg"
        cv2.imwrite(str(out_path), title)
        print(f"  {fname}: GT {len(gt_boxes)}개 / 검출 {len(det_boxes)}개 → {out_path.name}")

    print(f"\n완료 — {OUT_DIR}")


if __name__ == "__main__":
    main()
