"""zone_tile.py — 위험구역 한정 타일 재검출 (B9, 가산 레이어).

광역 CCTV 에서 작은 작업자(26~64px)가 일반 검출 임계에 묻혀 zone_intrusion recall 이
떨어지는 문제(B8 실측: 0%→구역타일 89~95%)를 보완한다. 위험구역 폴리곤의 바운딩박스만
크롭·확대해 재검출하여, zone 내부의 놓친 person 박스를 회수한다.

★ 코어 무의존: detector 를 함수로 주입받는다(detect_fn). guard/rfdetr 를 import 하지 않아
  테스트 용이 + 순환 없음. 반환 박스는 **zone_intrusion 판정 전용**으로만 쓴다(공유 detections
  에 병합하지 않는다 — proximity/crowd/motion/PPE 오염 방지, B9 확인1).

detect_fn(bgr_image) -> list[{"label": str, "bbox": [x1,y1,x2,y2](이미지 정규화 0~1), "conf": float}]
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:                     # numpy 는 타입검사 전용(런타임 import 불필요)
    import numpy as np


def zone_bbox_px(zone_poly: list, W: int, H: int) -> tuple[int, int, int, int]:
    """정규화 폴리곤 → 픽셀 바운딩박스(x0,y0,x1,y1). 프레임 경계로 클램프."""
    xs = [p[0] for p in zone_poly]
    ys = [p[1] for p in zone_poly]
    x0 = max(0, int(min(xs) * W)); y0 = max(0, int(min(ys) * H))
    x1 = min(W, int(max(xs) * W)); y1 = min(H, int(max(ys) * H))
    return x0, y0, x1, y1


def zone_tile_detect(frame: "np.ndarray", zone_poly: list, detect_fn: Callable,
                     thr: float = 0.1, min_h_px: int = 15, upscale: float = 2.0) -> list:
    """위험구역 크롭을 upscale 배 확대해 detect_fn 으로 재검출 → zone 내부 person 박스(원본 정규화).

    필터: label==person · conf>=thr · 박스 높이>=min_h_px(노이즈 슬라이버 제거).
    upscale 은 detector 에 넘기는 이미지 확대율(작은 사람 해상도↑)이며 반환 좌표계는 원본 프레임.
    """
    if not zone_poly or len(zone_poly) < 3:
        return []
    import cv2
    H, W = frame.shape[:2]
    zx0, zy0, zx1, zy1 = zone_bbox_px(zone_poly, W, H)
    zw, zh = zx1 - zx0, zy1 - zy0
    if zw < 2 or zh < 2:
        return []
    crop = frame[zy0:zy1, zx0:zx1]
    big = cv2.resize(crop, (max(1, int(zw * upscale)), max(1, int(zh * upscale))))
    out = []
    for d in detect_fn(big) or []:
        if d.get("label") != "person" or float(d.get("conf", 1.0)) < thr:
            continue
        bx1, by1, bx2, by2 = d["bbox"]                      # big(=crop) 정규화 0~1
        px1, py1 = zx0 + bx1 * zw, zy0 + by1 * zh           # → 원본 픽셀
        px2, py2 = zx0 + bx2 * zw, zy0 + by2 * zh
        if (py2 - py1) < min_h_px:                          # 높이 필터(노이즈)
            continue
        out.append({"label": "person", "conf": d.get("conf"),
                    "bbox": [px1 / W, py1 / H, px2 / W, py2 / H]})   # 원본 정규화
    return out


def foot_in_zone(bbox: list, zone_poly: list) -> bool:
    """정규화 person bbox 의 발 위치(하단중앙)가 zone 폴리곤 내부인지 — _derive 의 zone_intrusion 판정과 동일 규칙."""
    x1, y1, x2, y2 = bbox
    fx, fy = (x1 + x2) / 2, y2
    n = len(zone_poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = zone_poly[i]
        xj, yj = zone_poly[j]
        if ((yi > fy) != (yj > fy)) and (fx < (xj - xi) * (fy - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside
