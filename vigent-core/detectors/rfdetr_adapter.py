"""detectors.rfdetr_adapter — RF-DETR(Apache-2.0) 검출 백엔드. ultralytics(AGPL) 대체(T10a person).

RFDETRNano: COCO 80종 사전학습(person 포함). weights 지정 시 커스텀 체크포인트(.pth) 로드.
장치는 스스로 선택(prefer_mps=True) — RF-DETR 은 macOS MPS 다회추론 크래시 이슈가 없어(YOLO 와 달리)
MPS 를 써 빠르다(probe: person 33.8ms/frame). 박스 표준화는 base.finalize_box 공용 → YOLO 와 동일 규칙.

절대 저하 없음(§2): 로딩·추론 실패는 예외로 올려 guard 가 해당 슬롯만 비활성(나머지 정상).
"""
from __future__ import annotations

from typing import Any

from .base import BaseDetector, finalize_box

# 세로형 입력에서만 정사각 패딩(coord-letterbox). H/W(세로/가로 비)가 이 값을 넘으면 패딩한다.
#   근거(실측 scratchpad/coord_onset.py): 가로형(H/W<1)·정사각(1.0)은 좌표오차 ≤2px 로 정상이나,
#   세로형(H/W>1)은 5:4(1.25)에서도 15~23px 로 불안정(RF-DETR 내부 리사이즈가 세로를 왜곡).
#   → 세로형 전체를 패딩 대상으로. 1.05 여유는 '정확한 정사각'(패딩 무의미)과 '모든 가로형'을 확실히 제외해,
#     가로형은 기존 경로 그대로(유효해상도 보존 → 작은 사람 검출 저하 방지, B8) 타게 한다.
PAD_ASPECT_TALL = 1.05


class RfdetrDetector(BaseDetector):
    backend = "rfdetr"

    def __init__(self, weights: str, label_normalize: dict, junk: set):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # device 모듈 경로
        import device as _device
        from rfdetr import RFDETRNano  # lazy import
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
        import numpy as np
        from PIL import Image
        from rfdetr.util.coco_classes import COCO_CLASSES
        h, w = image_bgr.shape[:2]
        # ★세로형 좌표 정확도(coord-letterbox): 세로형(H/W>PAD_ASPECT_TALL)이면 입력을 정사각으로 회색패딩해
        #   종횡비 1:1 로 만든 뒤 추론 → RF-DETR 내부 리사이즈 왜곡 제거. 반환 박스는 아래서 un-pad 로 원좌표 복원.
        #   가로형·정사각은 pad=False(기존 경로 그대로). finalize_box 정규화 기준은 항상 '원본 w,h'.
        pad = h > w * PAD_ASPECT_TALL
        if pad:
            side = max(h, w)
            proc = np.full((side, side, 3), 114, dtype=np.uint8)   # 회색(114) 정사각 캔버스
            ox, oy = (side - w) // 2, (side - h) // 2
            proc[oy:oy + h, ox:ox + w] = image_bgr                 # 원본을 가운데 배치
        else:
            proc, ox, oy = image_bgr, 0, 0
        pil = Image.fromarray(cv2.cvtColor(proc, cv2.COLOR_BGR2RGB))
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
            if pad:                                            # 정사각 좌표 → 원본 픽셀로 복원(un-pad)
                x1 -= ox; x2 -= ox; y1 -= oy; y2 -= oy
            d = finalize_box(raw, float(det.confidence[j]), x1, y1, x2, y2, w, h, self._ln, self._junk)
            if d is not None:
                out.append(d)
        return out
