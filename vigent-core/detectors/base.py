"""detectors.base — 검출 백엔드 공통 인터페이스 + 박스 표준화 (T10a).

어댑터는 모델 로딩 + 프레임 추론 + 박스 표준화까지 책임진다. guard 는 반환된 표준 박스에
기존 후처리(_nms/_track/signals·PPE 후필터)를 그대로 적용한다(후처리·임계 무수정).

출력 계약(모든 어댑터 공통) — 박스당 dict:
    {"label": 표준라벨, "raw_label": 모델원시라벨, "conf": float(0~1, 소수3),
     "bbox": [x1,y1,x2,y2] (프레임 대비 0~1 정규화, 소수4)}

라벨 정규화(LABEL_NORMALIZE)·잡음 제거(JUNK_LABELS)·좌표 정규화·반올림은 finalize_box 에서
공통 처리한다 → YOLO/RF-DETR 어느 백엔드든 동일 규칙(§2 저하0: 기존 YOLO 인라인 루프와 바이트 동일).
"""
from __future__ import annotations

from typing import Any


class BaseDetector:
    """검출 백엔드 공통 인터페이스."""

    backend = "base"

    def detect(self, image_bgr, conf: float, imgsz: int | None = None,
               augment: bool = False) -> list[dict[str, Any]]:
        """프레임 추론 → 표준 박스 목록(위 출력 계약). 구현 필수.

        conf: 검출기 임계(guard 가 슬롯별 DETECTOR_CONF/PPE 후필터 계산해 전달).
        imgsz/augment: 백엔드가 지원하면 반영(RF-DETR 은 자체 전처리 → 무시 가능).
        """
        raise NotImplementedError


def finalize_box(raw_label: str, conf: float, x1: float, y1: float, x2: float, y2: float,
                 w: int, h: int, label_normalize: dict, junk: set) -> dict[str, Any] | None:
    """원시 박스 → 표준 박스 dict. JUNK 라벨이면 None(그리지 않고 버림).

    ★ guard.py 기존 인라인 루프와 바이트 동일 로직(정규화·소수 자리)  — 저하0 보장의 핵심.
    """
    label = label_normalize.get(raw_label, raw_label)
    if label in junk:
        return None
    return {
        "label": label,
        "raw_label": raw_label,
        "conf": round(float(conf), 3),
        # 정규화 bbox(0~1) — 프론트가 캔버스 크기에 맞춰 그림
        "bbox": [round(x1 / w, 4), round(y1 / h, 4),
                 round(x2 / w, 4), round(y2 / h, 4)],
    }
