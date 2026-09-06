#!/usr/bin/env python3
"""[U-0/S-1] 놓친 NO-Hardhat·person 유형 분류 — dev 74장, 운영 경로(Q-1 앙상블) 기준.

★[U-1]의 증강 처방("원거리·흐림 위주로 CCTV 열화 증강")은 이 분류 결과가 전제다 — 분류가
다르면(원거리·흐림이 다수가 아니면) 처방 자체가 바뀌어야 한다.

정답지 - 검출(person+ppe 앙상블, 운용 임계)을 IoU>=0.5 로 매칭해 놓친(FN) GT 박스를 찾고, 각각을:
  - 크기(perf_improvement_plan.md §0 과 동일 기준: 대>5%/중1~5%/소<1% 프레임 면적 대비)
  - 흐림(라플라시안 분산 — 낮을수록 흐림. 참고로 잡힌(TP) 박스와 비교 분포도 낸다)
둘 다 객관적으로 재고, 크롭을 몽타주로 모아 저장한다(육안 유형 분류는 몽타주를 보고 별도 보고).

test 35장은 건드리지 않는다(dev만).
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

FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
OUT_DIR = field_eval("s1_miss_montage")
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))
IOU_MATCH = 0.50
CROP_MARGIN = 0.25   # 크롭 여백(맥락 확인용, 25%)
TILE = 160           # 몽타주 타일 한 변(px)
COLS = 8


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_gt(stem: str, cls: str) -> list[list[float]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if CLASSES[int(parts[0])] != cls:
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def _size_bucket(bbox: list[float]) -> str:
    area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
    if area > 0.05:
        return "대(>5%)"
    if area > 0.01:
        return "중(1~5%)"
    return "소(<1%)"


def _blur_score(img: np.ndarray, bbox: list[float], margin: float = 0.0) -> float:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0.0, x1 - bw * margin); x2 = min(1.0, x2 + bw * margin)
    y1 = max(0.0, y1 - bh * margin); y2 = min(1.0, y2 + bh * margin)
    px1, py1, px2, py2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
    if px2 - px1 < 4 or py2 - py1 < 4:
        return -1.0
    crop = img[py1:py2, px1:px2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _crop_tile(img: np.ndarray, bbox: list[float], label: str) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0.0, x1 - bw * CROP_MARGIN); x2 = min(1.0, x2 + bw * CROP_MARGIN)
    y1 = max(0.0, y1 - bh * CROP_MARGIN); y2 = min(1.0, y2 + bh * CROP_MARGIN)
    px1, py1, px2, py2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
    px2, py2 = max(px2, px1 + 1), max(py2, py1 + 1)
    crop = img[py1:py2, px1:px2]
    tile = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_LINEAR)
    cv2.rectangle(tile, (2, 2), (TILE - 2, TILE - 2), (0, 0, 255), 1)
    cv2.putText(tile, label, (3, TILE - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1, cv2.LINE_AA)
    return tile


def _montage(tiles: list[np.ndarray], out_path: Path) -> None:
    if not tiles:
        return
    rows = (len(tiles) + COLS - 1) // COLS
    canvas = np.full((rows * TILE, COLS * TILE, 3), 30, dtype=np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, COLS)
        canvas[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE] = t
    cv2.imwrite(str(out_path), canvas)


def analyse(cls: str, label_kr: str) -> None:
    guard = bq._build_guard()
    fn_rows: list[dict[str, Any]] = []
    tp_blur: list[float] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gts = _load_gt(stem, cls)
        if not gts:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds = [d for d in out.get("detections", []) if d.get("label") == cls]

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
            if gi in gt_hit:
                tp_blur.append(_blur_score(img, g))
            else:
                fn_rows.append({"file": fname, "bbox": g, "img": img,
                                "size": _size_bucket(g), "blur": _blur_score(img, g)})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tiles = []
    for r in fn_rows:
        tag = f"{r['size']} blur={r['blur']:.0f}"
        tiles.append(_crop_tile(r["img"], r["bbox"], tag))
    montage_path = OUT_DIR / f"missed_{cls.replace(' ', '_')}.jpg"
    _montage(tiles, montage_path)

    size_counts: dict[str, int] = {}
    for r in fn_rows:
        size_counts[r["size"]] = size_counts.get(r["size"], 0) + 1
    fn_blur = [r["blur"] for r in fn_rows if r["blur"] >= 0]
    fn_blur_sorted = sorted(fn_blur)
    tp_blur_sorted = sorted(b for b in tp_blur if b >= 0)

    def _median(xs: list[float]) -> float:
        return xs[len(xs) // 2] if xs else -1.0

    print(f"\n=== 놓친 {label_kr}({cls}) — dev 기준, 총 {len(fn_rows)}건 ===")
    print(f"크기 분포: {size_counts}")
    print(f"흐림(라플라시안 분산, 낮을수록 흐림) — 놓친 것 median={_median(fn_blur_sorted):.1f} "
          f"(n={len(fn_blur_sorted)}) vs 잡은 것 median={_median(tp_blur_sorted):.1f} (n={len(tp_blur_sorted)})")
    print(f"몽타주: {montage_path}")
    for r in fn_rows:
        print(f"  {r['file']}: size={r['size']} blur={r['blur']:.0f}")


def main() -> None:
    analyse("NO-Hardhat", "NO-Hardhat")
    analyse("person", "person")


if __name__ == "__main__":
    main()
