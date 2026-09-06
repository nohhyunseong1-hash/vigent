#!/usr/bin/env python3
"""[X-4a] "가림 사례" 채점용 부분집합 정의 — dev person GT 중 현행 체크포인트가 놓친 50건.

★정의(규칙7 명시): 이 부분집합은 실측 가림 라벨이 아니라 **현행 ppe_rfdetr_v1의 놓침(FN) 집합
그 자체**다. [S-1](`benchmarks/s1_miss_montage.md`)가 이 50건을 몽타주 육안 검토로 "가림·특이
자세가 지배적"이라고 이미 확인했으므로, "신규 체크포인트가 학습 목표(가림 강건성)를 실제로
달성했는가"를 묻는 가장 직접적인 대조군으로 재사용한다. 정밀한 인스턴스 단위 가림도(%) 라벨은
아니다 — "현행 모델이 놓쳤고 육안상 가림이 지배적이던 GT 집합"이라는 프록시.

출력: data/field_eval/person_occlusion_subset.json (file+bbox 목록, [X-4b] 채점에서 그대로
재사용 — 신규 체크포인트마다 매번 다시 계산하지 않고 고정된 분모로 비교한다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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
from isolated_detect import detect_isolated  # noqa: E402

FRAMES_DIR = media("field_eval") / "frames"
LABELS_DIR = media("field_eval") / "labels"
CLASSES = [c.strip() for c in (media("field_eval") / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((media("field_eval") / "dev_test_split.json").read_text(encoding="utf-8"))
OUT_PATH = media("field_eval") / "person_occlusion_subset.json"
IOU_MATCH = 0.50


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_gt(stem: str) -> list[list[float]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if CLASSES[int(parts[0])] != "person":
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def main() -> None:
    guard = bq._build_guard()   # 현행 ppe_rfdetr_v1 (vision.yaml 기본 슬롯)
    missed: list[dict] = []
    total_gt = 0

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gts = _load_gt(stem)
        if not gts:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds = [d for d in out.get("detections", []) if d.get("label") == "person"]

        pairs = []
        for gi, g in enumerate(gts):
            for pi, p in enumerate(preds):
                v = _iou(g, p["bbox"])
                if v >= IOU_MATCH:
                    pairs.append((v, gi, pi))
        pairs.sort(key=lambda x: -x[0])
        gt_hit: set[int] = set()
        pred_used: set[int] = set()
        for _v, gi, pi in pairs:
            if gi in gt_hit or pi in pred_used:
                continue
            gt_hit.add(gi)
            pred_used.add(pi)

        for gi, g in enumerate(gts):
            total_gt += 1
            if gi not in gt_hit:
                missed.append({"file": fname, "bbox": g})

    print(f"dev person 전체 GT: {total_gt}건, 현행 체크포인트 놓침(가림 부분집합 후보): {len(missed)}건")

    OUT_PATH.write_text(json.dumps({
        "created": "2026-08-10",
        "source": "현행 ppe_rfdetr_v1 dev person FN — S-1 육안 확인(가림·특이자세 지배적)에 근거한 프록시",
        "definition_limits": "정밀 인스턴스 단위 가림도(%) 라벨 아님 — 규칙7",
        "baseline_checkpoint": "vigent-core/weights/ppe_rfdetr_v1.pth",
        "count": len(missed),
        "items": missed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
