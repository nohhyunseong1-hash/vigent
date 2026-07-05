"""detectors.rfdetr_adapter — RF-DETR(Apache-2.0) 검출 백엔드. ultralytics(AGPL) 대체(T10a person).

RFDETRNano: COCO 80종 사전학습(person 포함). weights 지정 시 커스텀 체크포인트(.pth) 로드.
장치는 스스로 선택(prefer_mps=True) — RF-DETR 은 macOS MPS 다회추론 크래시 이슈가 없어(YOLO 와 달리)
MPS 를 써 빠르다(probe: person 33.8ms/frame). 박스 표준화는 base.finalize_box 공용 → YOLO 와 동일 규칙.

절대 저하 없음(§2): 로딩·추론 실패는 예외로 올려 guard 가 해당 슬롯만 비활성(나머지 정상).
"""
from __future__ import annotations

from typing import Any

from .base import BaseDetector, finalize_box


class RfdetrDetector(BaseDetector):
    backend = "rfdetr"

    def __init__(self, weights: str, label_normalize: dict, junk: set):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # device 모듈 경로
        import device as _device
        from rfdetr import RFDETRNano   # lazy import
        dev = _device.pick_device(prefer_mps=True)   # RF-DETR 은 MPS 안전
        kwargs: dict[str, Any] = {"device": dev}
        if weights:
            kwargs["pretrain_weights"] = weights   # 커스텀 파인튜닝(있으면), 없으면 COCO 사전학습
        self.model = RFDETRNano(**kwargs)
        try:
            self.model.optimize_for_inference()
        except Exception:  # noqa: BLE001  최적화 실패해도 추론은 가능
            pass
        self.device = dev
        self._ln = label_normalize
        self._junk = junk
        # 클래스 매핑: COCO 사전학습(weights="")은 COCO_CLASSES. 커스텀 파인튜닝(weights 지정)은
        #   모델 자체 class_names(0-indexed, 예: ['forklift']). class_id ≥ 클래스수 = DETR 배경/no-object → 무시.
        #   (COCO_CLASSES 하드코딩은 커스텀 모델을 오매핑 → 실측 근거로 분기: T10b eval_rfdetr_custom.py 참조)
        self._custom_names = list(getattr(self.model, "class_names", []) or []) if weights else None

    def detect(self, image_bgr, conf: float, imgsz: int | None = None,
               augment: bool = False) -> list[dict[str, Any]]:
        import cv2
        from PIL import Image
        from rfdetr.util.coco_classes import COCO_CLASSES
        h, w = image_bgr.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        det = self.model.predict(pil, threshold=conf)   # 검출기 임계를 그대로 사용(운용점 일치)
        out: list[dict[str, Any]] = []
        xyxy = getattr(det, "xyxy", [])
        for j in range(len(xyxy)):
            cid = int(det.class_id[j])
            if self._custom_names is not None:                 # 커스텀 파인튜닝: 자체 class_names(0-indexed)
                if not (0 <= cid < len(self._custom_names)):
                    continue                                   # 범위 밖 = 배경/no-object → 버림
                raw = self._custom_names[cid]
            else:                                              # COCO 사전학습(person 등): 기존 경로 불변
                raw = COCO_CLASSES[cid]
            x1, y1, x2, y2 = (float(v) for v in xyxy[j])
            d = finalize_box(raw, float(det.confidence[j]), x1, y1, x2, y2, w, h, self._ln, self._junk)
            if d is not None:
                out.append(d)
        return out
