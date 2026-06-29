"""rf-detr 백엔드 서비스 — 웹 화면이 호출하는 탐지·추적·위험구역·VLM (permissive).

- 모델은 1회 로드해 재사용(서버 수명 동안).
- detect(): 프레임 → rf-detr 사람탐지 → SORTTracker 추적 → 위험구역 침입 판정.
- summarize(): 이벤트 프레임 → mlx-vlm 위험요약 JSON(무겁고 느림, 프론트가 드물게 호출).
전부 로컬·permissive(rfdetr/trackers Apache-2.0, supervision/mlx-vlm MIT).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def _load_zone(theme: str = "safety"):
    """vision.yaml + danger_zone.json 에서 위험구역(정규화 폴리곤)·임계값."""
    import yaml
    vy = yaml.safe_load(open(ROOT / "themes" / theme / "vision.yaml", encoding="utf-8"))
    jud = vy.get("judgment", {}) or {}
    thr = float(jud.get("detect_threshold", 0.4))
    zpath = (jud.get("zones", {}) or {}).get("danger_zones")
    pts = []
    if zpath and (ROOT / zpath).exists():
        z = json.load(open(ROOT / zpath, encoding="utf-8"))
        pts = [(p["x"], p["y"]) for p in z.get("points", [])]
    return pts, thr


def _point_in_poly(x, y, poly) -> bool:
    """점(x,y)이 폴리곤(픽셀좌표 Nx2) 내부인지 — ray casting."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


class RFDetrService:
    """rf-detr 탐지 + 추적 + 위험구역. 지연 로드 싱글톤."""

    def __init__(self):
        self._model = None
        self._tracker = None

    def _ensure(self):
        if self._model is not None:
            return
        import torch
        from rfdetr import RFDETRNano
        from trackers import SORTTracker
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = RFDETRNano(device=dev)
        try:
            self._model.optimize_for_inference()
        except Exception:  # noqa: BLE001
            pass
        self._tracker = SORTTracker()
        self.device = dev

    def detect(self, image_bgr: np.ndarray) -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 bbox·라벨·id 목록 + 위험구역 침입."""
        self._ensure()
        import cv2
        import supervision as sv
        from PIL import Image
        from rfdetr.util.coco_classes import COCO_CLASSES

        h, w = image_bgr.shape[:2]
        pts, thr = _load_zone("safety")              # 매 프레임 설정 반영(화면서 구역 바꾸면 즉시)
        det = self._model.predict(
            Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)), threshold=thr)
        names = [COCO_CLASSES[c] for c in det.class_id]   # 80종 전부 유지(사람만 거르지 않음)

        # 위험구역 침입은 '사람'에만 적용 → 좌표가 구역 안인지 판정
        zone = None
        if len(pts) >= 3:
            zone = sv.PolygonZone(polygon=(np.array(pts) * [w, h]).astype(int))
            zone.trigger(det)            # 내부 카운트 갱신(개별 마스크는 아래서 직접 계산)
        poly = (np.array(pts) * [w, h]) if len(pts) >= 3 else None

        def _in_zone(box):
            if poly is None:
                return False
            cx, cy = (box[0] + box[2]) / 2, box[3]          # 발 위치(하단 중앙)
            return bool(_point_in_poly(cx, cy, poly))

        out, n_in = [], 0
        for i in range(len(det)):
            label = names[i]
            x1, y1, x2, y2 = (float(v) for v in det.xyxy[i])
            inz = (label == "person") and _in_zone((x1, y1, x2, y2))
            if inz:
                n_in += 1
            out.append({
                "label": label,
                "conf": round(float(det.confidence[i]), 2),
                "id": -1,
                "in_zone": inz,
                "bbox": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
            })
        person_count = sum(1 for d in out if d["label"] == "person")
        return {"detections": out, "person_count": person_count,
                "intrusion": {"count": n_in, "ids": []},
                "device": getattr(self, "device", "?")}


class VLMService:
    """mlx-vlm 위험요약. 지연 로드 싱글톤(무겁다)."""

    def __init__(self):
        self._vlm = None

    def summarize_bgr(self, image_bgr: np.ndarray, prompt: str | None = None) -> dict[str, Any]:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "ml"))
        import cv2
        if self._vlm is None:
            from vlm_risk_summary import RiskVLM
            self._vlm = RiskVLM()
        tmp = Path("/tmp/vigent_vlm_event.jpg")
        cv2.imwrite(str(tmp), image_bgr)
        return self._vlm.summarize(str(tmp), prompt=prompt)

    def quick_bgr(self, image_bgr: np.ndarray, prompt: str,
                  max_tokens: int = 64, max_side: int = 640) -> dict[str, Any]:
        """빠른 단발 질의(PPE 등 단답) — 작은 이미지·짧은 토큰·재시도 없음."""
        import sys
        import cv2
        sys.path.insert(0, str(Path(__file__).resolve().parent / "ml"))
        if self._vlm is None:
            from vlm_risk_summary import RiskVLM
            self._vlm = RiskVLM()
        tmp = Path("/tmp/vigent_vlm_quick.jpg")
        cv2.imwrite(str(tmp), image_bgr)
        return self._vlm.quick(str(tmp), prompt, max_tokens=max_tokens, max_side=max_side)


# 서버 전역 싱글톤
rfdetr = RFDetrService()
vlm = VLMService()
