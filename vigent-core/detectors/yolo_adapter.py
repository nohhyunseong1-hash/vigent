"""detectors.yolo_adapter — 기존 ultralytics YOLO 경로를 어댑터로 감싼다(§2 저하0).

YOLO(.pt) 로딩·추론은 guard.py 기존 코드와 동일(같은 predict 인자·같은 device).
박스 표준화만 base.finalize_box 공용으로 위임 → 라벨정규화·좌표정규화가 기존과 바이트 동일.

■ 지위: 롤백 안전망. T10b 로 전 검출 슬롯(person/ppe/fire_smoke/forklift)이 RF-DETR 이관 완료되어
  이 경로는 배포에서 미사용. **현장 검증(T10c-V) 완료까지 존치**, 이후 제거 검토(제거 조건은 FINDINGS 백로그 등재).
■ 라이선스(copyleft 0 유지): `ultralytics`(AGPL-3.0)는 아래 **지연 import**이며 **배포 requirements 에 미포함**.
  backend=yolo 는 측정/롤백 시에만 사용 가능하고 그때는 별도 설치(requirements-eval.txt) 필요.
  → 배포물에 AGPL 코드·의존성 미포함 → **copyleft 0 유지**(이 파일 자체는 VIGENT 코드, AGPL 아님).
■ 롤백 절차: vision.yaml `backend.<slot>=yolo` 전환 + 측정 requirements 설치(ultralytics) + **서비스 재시작**
  (F-6 운영 리스크: tuning/설정 변경은 재시작 없이는 라이브 미반영).
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
