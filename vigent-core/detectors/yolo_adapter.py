"""detectors.yolo_adapter — 기존 ultralytics YOLO 경로를 어댑터로 감싼다(§2 저하0).

YOLO(.pt) 로딩·추론은 guard.py 기존 코드와 동일(같은 predict 인자·같은 device).
박스 표준화만 base.finalize_box 공용으로 위임 → 라벨정규화·좌표정규화가 기존과 바이트 동일.
⚠️ ultralytics 는 AGPL-3.0(CLAUDE.md §6). person 은 RF-DETR 로 이관(T10a),
   ppe/fire_smoke/forklift 는 T10b 에서 RF-DETR 모델 학습 후 이관 예정 — 그때까진 이 경로 유지.
"""
from __future__ import annotations

from typing import Any

from .base import BaseDetector, finalize_box


class YoloDetector(BaseDetector):
    backend = "yolo"

    def __init__(self, path: str, device: str, default_imgsz: int,
                 label_normalize: dict, junk: set):
        from ultralytics import YOLO   # lazy import — 백엔드 사용 시에만 로드
        self.model = YOLO(path)
        self.device = device
        self.default_imgsz = default_imgsz
        self._ln = label_normalize
        self._junk = junk

    def detect(self, image_bgr, conf: float, imgsz: int | None = None,
               augment: bool = False) -> list[dict[str, Any]]:
        h, w = image_bgr.shape[:2]
        # guard 기존 호출과 동일: 해상도 override·(오프라인)TTA·검출기별 임계·device 고정
        res = self.model.predict(image_bgr, verbose=False, conf=conf,
                                 imgsz=imgsz or self.default_imgsz,
                                 augment=augment, device=self.device)[0]
        names = self.model.names
        out: list[dict[str, Any]] = []
        for b in res.boxes:
            cls_id = int(b.cls[0])
            raw = names.get(cls_id, str(cls_id))
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            d = finalize_box(raw, float(b.conf[0]), x1, y1, x2, y2, w, h, self._ln, self._junk)
            if d is not None:
                out.append(d)
        return out

    @property
    def names(self):   # 진단·호환용
        return self.model.names
