#!/usr/bin/env python3
"""[V-0] 놓친 NO-Hardhat 40건 — 번호 매긴 판정용 격자 시트.

s1_miss_montage.py 와 같은 40건(dev, 운영 경로 기준 FN)을 다시 크롭하되, 이번엔 크기/흐림
수치 대신 **번호만** 크게 붙인다 — 사용자가 "안전모/맨머리 구분 가능(O) vs 불가(X)"를 번호로
답하기 위한 판정용 시트. 판정 로직 없음(그림만 준비).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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

FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
OUT_PATH = field_eval("s1_miss_montage/no_hardhat_judge_sheet.jpg")
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))
IOU_MATCH = 0.50
CROP_MARGIN = 0.30   # 판정용이라 여백을 조금 더 줌(목 주변까지 보이게)
TILE = 200
COLS = 8


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
        if CLASSES[int(parts[0])] != "NO-Hardhat":
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def main() -> None:
    guard = bq._build_guard()
    entries: list[tuple[str, list[float], np.ndarray]] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gts = _load_gt(stem)
        if not gts:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds = [d for d in out.get("detections", []) if d.get("label") == "NO-Hardhat"]
        pairs = []
        for gi, g in enumerate(gts):
            for pi, p in enumerate(preds):
                if _iou(g, p["bbox"]) >= IOU_MATCH:
                    pairs.append((_iou(g, p["bbox"]), gi, pi))
        pairs.sort(key=lambda x: -x[0])
        gt_hit: set[int] = set()
        pred_used: set[int] = set()
        for _v, gi, pi in pairs:
            if gi in gt_hit or pi in pred_used:
                continue
            gt_hit.add(gi)
            pred_used.add(pi)
        for gi, g in enumerate(gts):
            if gi not in gt_hit:
                entries.append((fname, g, img))

    print(f"놓친 NO-Hardhat: {len(entries)}건")
    tiles = []
    for idx, (fname, bbox, img) in enumerate(entries, start=1):
        h, w = img.shape[:2]
        x1, y1, x2, y2 = bbox
        bw, bh = x2 - x1, y2 - y1
        x1 = max(0.0, x1 - bw * CROP_MARGIN); x2 = min(1.0, x2 + bw * CROP_MARGIN)
        y1 = max(0.0, y1 - bh * CROP_MARGIN); y2 = min(1.0, y2 + bh * CROP_MARGIN)
        px1, py1, px2, py2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
        px2, py2 = max(px2, px1 + 1), max(py2, py1 + 1)
        crop = img[py1:py2, px1:px2]
        tile = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_LINEAR)
        # 번호 배지(왼쪽 위, 눈에 잘 띄게)
        cv2.rectangle(tile, (0, 0), (34, 24), (0, 0, 0), -1)
        cv2.putText(tile, str(idx), (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.rectangle(tile, (1, 1), (TILE - 2, TILE - 2), (0, 0, 255), 1)
        tiles.append(tile)

    rows = (len(tiles) + COLS - 1) // COLS
    canvas = np.full((rows * TILE, COLS * TILE, 3), 30, dtype=np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, COLS)
        canvas[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE] = t
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT_PATH), canvas)
    print(f"판정 시트: {OUT_PATH}")

    # 번호 -> 파일명 대응표(사용자가 특정 번호를 다시 원본 크기로 보고 싶을 때 참고)
    idx_map_path = OUT_PATH.with_suffix(".json")
    idx_map = [{"idx": i, "file": f, "bbox": b} for i, (f, b, _img) in enumerate(entries, start=1)]
    idx_map_path.write_text(json.dumps(idx_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"번호->파일 대응표: {idx_map_path}")


if __name__ == "__main__":
    main()
