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
        names = np.array([COCO_CLASSES[c] for c in det.class_id])
        det = det[names == "person"]
        det = self._tracker.update(det)

        in_mask = None
        if len(pts) >= 3:
            zone = sv.PolygonZone(polygon=(np.array(pts) * [w, h]).astype(int))
            in_mask = zone.trigger(det)

        out = []
        ids = det.tracker_id if det.tracker_id is not None else [-1] * len(det)
        for i in range(len(det)):
            x1, y1, x2, y2 = (float(v) for v in det.xyxy[i])
            out.append({
                "label": "person",
                "conf": round(float(det.confidence[i]), 2),
                "id": int(ids[i]),
                "in_zone": bool(in_mask[i]) if in_mask is not None else False,
                "bbox": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
            })
        n_in = int(in_mask.sum()) if in_mask is not None else 0
        return {"detections": out, "person_count": len(out),
                "intrusion": {"count": n_in, "ids": [d["id"] for d in out if d["in_zone"]]},
                "device": getattr(self, "device", "?")}


class VLMService:
    """mlx-vlm 위험요약. 지연 로드 싱글톤(무겁다)."""

    def __init__(self):
        self._vlm = None

    def summarize_bgr(self, image_bgr: np.ndarray) -> dict[str, Any]:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "ml"))
        import cv2
        if self._vlm is None:
            from vlm_risk_summary import RiskVLM
            self._vlm = RiskVLM()
        tmp = Path("/tmp/vigent_vlm_event.jpg")
        cv2.imwrite(str(tmp), image_bgr)
        return self._vlm.summarize(str(tmp))


# 서버 전역 싱글톤
rfdetr = RFDetrService()
vlm = VLMService()
