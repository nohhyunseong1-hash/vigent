"""Guard — [감지] 실시간 탐지·추적·이벤트 발생 (§15 2번: 딥러닝 탐지 계층)

vision.yaml 의 detector 슬롯(person/ppe/forklift/fire_smoke)에서 실제 .pt 모델을
1회 로드해 캐시하고, 프레임 추론 → 박스·클래스·confidence 를 반환한다.

절대 저하 없음(§2-1):
  - 모델 로드/추론이 실패하면 해당 검출기만 비활성, 나머지는 정상 동작.
  - 모델이 아예 없으면(폴백 슬롯) 그 검출기는 건너뛴다. 프론트 휴리스틱이 보완.

라벨 정규화(D층 이슈):
  PPE 모델 실제 라벨은 'Safety Vest'/'NO-Safety Vest'(공백)인데, vision.yaml·판단 규칙은
  'Safety-Vest'/'NO-Safety-Vest'(하이픈)를 기대한다 → 여기서 표준 라벨로 통일한다.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import BaseAgent

# 모델이 내보내는 원시 라벨 → VIGENT 표준 라벨(규칙이 비교하는 문자열)
LABEL_NORMALIZE = {
    "NO-Safety Vest": "NO-Safety-Vest",
    "Safety Vest": "Safety-Vest",
    "NO-Safety-Vest": "NO-Safety-Vest",
    "Safety-Vest": "Safety-Vest",
    "Hardhat": "Hardhat", "NO-Hardhat": "NO-Hardhat",
}
# PPE 미착용 판정에 쓰는 표준 라벨
PPE_MISSING_LABELS = {"NO-Hardhat", "NO-Safety-Vest"}


class GuardAgent(BaseAgent):
    name = "Guard"
    role = "감지: 실시간 탐지·추적·이벤트 스트림 생성"

    # detector 슬롯 id → 추론 시 기본 confidence 임계값
    DEFAULT_CONF = 0.35

    def __init__(self, config: Any):
        super().__init__(config)
        self._models: dict[str, Any] = {}      # id → YOLO (지연 로드 캐시)
        self._load_errors: dict[str, str] = {}
        # config.slots 에서 실제 .pt 파일로 해석된 detector 슬롯만 추린다
        self._slot_path: dict[str, str] = {}
        for s in config.slots:
            if s.slot in ("person", "ppe", "forklift", "fire_smoke") and s.source == "model" and s.active:
                self._slot_path[s.slot] = s.active

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "detectors_available": list(self._slot_path.keys()),
                "loaded": list(self._models.keys()),
                "load_errors": self._load_errors}

    def _get_model(self, slot: str):
        """슬롯 모델을 1회 로드해 캐시. 실패하면 None(해당 검출기만 비활성)."""
        if slot in self._models:
            return self._models[slot]
        path = self._slot_path.get(slot)
        if not path:
            return None
        try:
            from ultralytics import YOLO
            self._models[slot] = YOLO(path)
            return self._models[slot]
        except Exception as ex:  # noqa: BLE001  로드 실패해도 죽지 않는다
            self._load_errors[slot] = f"{type(ex).__name__}: {ex}"
            self._models[slot] = None
            return None

    def detect(self, image_bgr: np.ndarray, detectors: list[str] | None = None,
               conf: float | None = None) -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 라벨·confidence·정규화 bbox(0~1) 목록 + 파생 신호.

        image_bgr: cv2 BGR numpy 배열
        detectors: 돌릴 검출기 id 목록(기본 person·ppe·forklift; fire 는 명시 시)
        """
        conf = self.DEFAULT_CONF if conf is None else conf
        want = detectors or ["person", "ppe", "forklift"]
        h, w = image_bgr.shape[:2]
        detections: list[dict[str, Any]] = []
        used: list[str] = []

        for slot in want:
            model = self._get_model(slot)
            if model is None:
                continue
            try:
                res = model.predict(image_bgr, verbose=False, conf=conf)[0]
            except Exception as ex:  # noqa: BLE001  추론 실패해도 나머지 진행
                self._load_errors[slot] = f"predict: {type(ex).__name__}: {ex}"
                continue
            used.append(slot)
            names = model.names
            for b in res.boxes:
                cls_id = int(b.cls[0])
                raw = names.get(cls_id, str(cls_id))
                label = LABEL_NORMALIZE.get(raw, raw)
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                detections.append({
                    "detector": slot,
                    "label": label, "raw_label": raw,
                    "conf": round(float(b.conf[0]), 3),
                    # 정규화 bbox(0~1) — 프론트가 캔버스 크기에 맞춰 그림
                    "bbox": [round(x1 / w, 4), round(y1 / h, 4),
                             round(x2 / w, 4), round(y2 / h, 4)],
                })

        # 파생 신호(딥러닝 → 규칙 가산용)
        person_count = sum(1 for d in detections if d["label"].lower() == "person")
        ppe_missing_hits = [d for d in detections if d["label"] in PPE_MISSING_LABELS]
        # ppe_conf: 미착용 탐지 최고 confidence(있으면 Analyst 가산용으로 전달)
        ppe_conf = max((d["conf"] for d in ppe_missing_hits), default=0.0)

        return {
            "detectors_used": used,
            "person_count": person_count,
            "detections": detections,
            "signals": {
                "ppe_missing": bool(ppe_missing_hits),
                "ppe_conf": ppe_conf,
                "forklift_present": any(d["label"].lower() == "forklift" for d in detections),
            },
        }
