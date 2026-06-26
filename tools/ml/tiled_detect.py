"""tiled_detect.py — 타일링 추론(SAHI 방식): 다중·소형 객체 인식 강화

큰 이미지를 겹치는 타일로 쪼개 각 타일을 탐지한 뒤, 좌표를 원본으로 되돌려 합친다.
멀리 있는 작은 사람·붐비는 장면에서 일반 추론보다 많이 잡는다(군중·원거리 협착에 유리).

trade-off: 타일 수만큼 추론 → 느려짐. 정확도(소형객체) ↔ 속도.

사용(데모): python tools/ml/tiled_detect.py <이미지경로>
함수: tiled_detect(image_bgr, guard, detectors, tile=640, overlap=0.2)
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "vigent-core"))


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _merge(dets, iou_thr=0.5):
    """라벨별 NMS — 타일 경계 중복 박스 정리."""
    out = []
    for d in sorted(dets, key=lambda x: -x["conf"]):
        k = str(d["label"]).lower()
        if any(str(o["label"]).lower() == k and _iou(o["bbox"], d["bbox"]) > iou_thr for o in out):
            continue
        out.append(d)
    return out


def tiled_detect(image_bgr, guard, detectors=("person",), tile=640, overlap=0.2):
    """타일링 추론 → 합친 detections(정규화 bbox). guard 의 추적기는 끄고 타일별 호출."""
    import cv2  # noqa: F401
    H, W = image_bgr.shape[:2]
    step = int(tile * (1 - overlap))
    xs = list(range(0, max(1, W - tile + 1), step)) or [0]
    ys = list(range(0, max(1, H - tile + 1), step)) or [0]
    if xs[-1] + tile < W:
        xs.append(W - tile)
    if ys[-1] + tile < H:
        ys.append(H - tile)
    all_dets = []
    for y0 in ys:
        for x0 in xs:
            x0c, y0c = max(0, x0), max(0, y0)
            crop = image_bgr[y0c:y0c + tile, x0c:x0c + tile]
            if crop.size == 0:
                continue
            ch, cw = crop.shape[:2]
            guard._tracks = []
            out = guard.detect(crop, detectors=list(detectors))
            for d in out.get("detections", []):
                bb = d["bbox"]   # 타일 정규화 → 원본 정규화
                gx1 = (x0c + bb[0] * cw) / W
                gy1 = (y0c + bb[1] * ch) / H
                gx2 = (x0c + bb[2] * cw) / W
                gy2 = (y0c + bb[3] * ch) / H
                all_dets.append({**d, "bbox": [gx1, gy1, gx2, gy2]})
    return _merge(all_dets)


def _count(guard, img, detectors, cls):
    guard._tracks = []
    out = guard.detect(img, detectors=list(detectors))
    return sum(1 for d in out.get("detections", []) if str(d["label"]).lower() == cls)


if __name__ == "__main__":
    import cv2
    import main
    path = sys.argv[1] if len(sys.argv) > 1 else "data/eval/clean/images/eval_00.jpg"
    img = cv2.imread(os.path.join(_ROOT, path) if not os.path.isabs(path) else path)
    bundle = main.STATE.get(main.DEFAULT_THEME) or main._load_theme(main.DEFAULT_THEME)
    guard = bundle["agents"].get("Guard")
    normal = _count(guard, img, ["person"], "person")
    tiled = tiled_detect(img, guard, detectors=["person"], tile=480, overlap=0.25)
    tiled_n = sum(1 for d in tiled if str(d["label"]).lower() == "person")
    print(f"이미지: {path}  ({img.shape[1]}x{img.shape[0]})")
    print(f"일반 추론 사람: {normal}명")
    print(f"타일링 추론 사람: {tiled_n}명  (소형·원거리 추가 포착)")
