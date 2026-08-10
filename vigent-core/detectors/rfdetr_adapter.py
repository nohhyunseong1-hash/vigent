"""detectors.rfdetr_adapter — RF-DETR(Apache-2.0) 검출 백엔드. ultralytics(AGPL) 대체(T10a person).

RFDETRNano: COCO 80종 사전학습(person 포함). weights 지정 시 커스텀 체크포인트(.pth) 로드.
장치는 스스로 선택(prefer_mps=True) — RF-DETR 은 macOS MPS 다회추론 크래시 이슈가 없어(YOLO 와 달리)
MPS 를 써 빠르다(probe: person 33.8ms/frame). 박스 표준화는 base.finalize_box 공용 → YOLO 와 동일 규칙.

절대 저하 없음(§2): 로딩·추론 실패는 예외로 올려 guard 가 해당 슬롯만 비활성(나머지 정상).

[Q-3, 2026-08-10] 해상도(imgsz)는 **로드 시점에 고정된다** — RF-DETR 은 `optimize_for_inference()`
로 모델을 그 시점 해상도로 컴파일해버려서, 그 뒤엔 다른 해상도를 주면 `ValueError: Resolution
mismatch`가 난다(실측 확인, `benchmarks/p3_1_resolution_ab_BLOCKED.md`). 그래서 `__init__`이
`resolution` 을 받아 로드 시점에 적용하고(호출자는 `config/tuning.yaml` `detect.imgsz`), 매 호출의
`detect(..., imgsz=)` 는 **참고용 검증만** 한다 — 로드된 해상도와 다르면 조용히 무시하지 않고
경고를 낸다(예전엔 매개변수를 받고 그냥 버렸다 — dead parameter, 재발 방지).
"""
from __future__ import annotations

import logging
from typing import Any

from .base import BaseDetector, finalize_box

_LOG = logging.getLogger("vigent.rfdetr_adapter")

# 세로형 입력에서만 정사각 패딩(coord-letterbox). H/W(세로/가로 비)가 이 값을 넘으면 패딩한다.
#   근거(실측 scratchpad/coord_onset.py): 가로형(H/W<1)·정사각(1.0)은 좌표오차 ≤2px 로 정상이나,
#   세로형(H/W>1)은 5:4(1.25)에서도 15~23px 로 불안정(RF-DETR 내부 리사이즈가 세로를 왜곡).
#   → 세로형 전체를 패딩 대상으로. 1.05 여유는 '정확한 정사각'(패딩 무의미)과 '모든 가로형'을 확실히 제외해,
#     가로형은 기존 경로 그대로(유효해상도 보존 → 작은 사람 검출 저하 방지, B8) 타게 한다.
PAD_ASPECT_TALL = 1.05

# [Q-3] RFDETRNano 는 해상도가 patch_size(16)*num_windows(2)=32 의 배수여야 한다(실측 확인:
#   32 배수가 아닌 값을 resolution 에 주면 optimize_for_inference() 가 AssertionError 로 죽는다 —
#   "Backbone requires input shape to be divisible by 32"). 아래 32는 RFDETRNanoConfig 기본값에서
#   읽은 상수(다른 크기 모델로 백엔드를 바꾸면 이 값도 같이 확인해야 함).
_RESOLUTION_BLOCK = 32


def _round_resolution(requested: int) -> int:
    """requested 를 _RESOLUTION_BLOCK 배수로 반올림(최소 그 값 1개는 보장)."""
    if requested % _RESOLUTION_BLOCK == 0:
        return requested
    rounded = max(_RESOLUTION_BLOCK, round(requested / _RESOLUTION_BLOCK) * _RESOLUTION_BLOCK)
    _LOG.warning("resolution=%d 는 %d의 배수가 아니라 %d로 반올림됨(RFDETRNano 백본 제약).",
                 requested, _RESOLUTION_BLOCK, rounded)
    return rounded


class RfdetrDetector(BaseDetector):
    backend = "rfdetr"

    def __init__(self, weights: str, label_normalize: dict, junk: set, resolution: int | None = None):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # device 모듈 경로
        import device as _device
        from rfdetr import RFDETRNano  # lazy import
        dev = _device.pick_device(prefer_mps=True)   # RF-DETR 은 MPS 안전
        kwargs: dict[str, Any] = {"device": dev}
        if weights:
            kwargs["pretrain_weights"] = weights   # 커스텀 파인튜닝(있으면), 없으면 COCO 사전학습
        if resolution:
            kwargs["resolution"] = _round_resolution(int(resolution))   # [Q-3] 로드 시점 해상도(없으면 기본 384)
        self.model = RFDETRNano(**kwargs)
        # [Q-3] 실제로 적용된 해상도를 모델 설정에서 그대로 읽는다(요청값이 block_size 배수가 아니면
        #   라이브러리가 조정할 수 있어, "요청값"이 아니라 "실제 로드값"을 신뢰한다).
        self.resolution = int(getattr(self.model.model_config, "resolution", resolution or 384))
        try:
            self.model.optimize_for_inference()
        except Exception:  # noqa: BLE001  최적화 실패해도 추론은 가능
            pass
        self.device = dev
        self._ln = label_normalize
        self._junk = junk
        self._imgsz_warned: set[int] = set()   # [Q-3] 같은 불일치값으로 매 프레임 로그 스팸 방지(1회만)
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
        # [Q-3] imgsz 는 로드 시점에 이미 고정됐다(RF-DETR optimize_for_inference() 제약, 클래스
        #   docstring 참고) — 호출별로 다시 바꿀 수 없다. 요청값이 로드된 해상도와 다르면(죽은
        #   매개변수로 조용히 버리지 않고) 경고를 낸다. 같은 값으로 반복 호출되는 게 보통이라(예:
        #   focus_active 5fps 루프) 값별로 1회만 경고해 로그 폭주를 막는다.
        if imgsz and imgsz != self.resolution and imgsz not in self._imgsz_warned:
            self._imgsz_warned.add(imgsz)
            _LOG.warning(
                "imgsz=%d 요청됐지만 이 모델은 해상도 %d로 이미 로드·최적화됨 — 호출별 변경 불가"
                "(RF-DETR optimize_for_inference() 제약). config/tuning.yaml detect.imgsz 를 바꾸고 "
                "재기동해야 실제로 적용된다. 이번 호출은 %d로 진행.",
                imgsz, self.resolution, self.resolution,
            )
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
