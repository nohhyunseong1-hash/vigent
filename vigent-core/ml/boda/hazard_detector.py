"""신규 안전 인식(위험요소) 모듈 — 가산식, 오탐 보수적.

기존 detector.evaluate_risk의 규칙은 그대로 두고, 이 모듈은 추가 위험요소를
'hazards' 리스트로 별도 제공한다. 각 항목은 (type, label, confidence, severity)
구조이며, 강한 신호일 때만 alert로 승격한다. 따라서 기존 알림 동작을 더
시끄럽게 만들지 않으면서 인식 범위만 넓힌다.

지원 항목:
- fire / smoke: 색상·밝기 휴리스틱 (가벼움, 모델 없이 동작). 전용 모델 가중치가
  있으면 융합하여 정확도를 올린다.
- smoking: 탐지 클래스에 담배/흡연 관련 클래스가 있을 때.
- fall_from_height: 고소작업 구역(상단) 사람 + 낙하 속도/자세 휴리스틱.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

SMOKING_CLASSES = {"cigarette", "cigarette_stick", "smoking", "vape", "e_cigarette", "lighter"}
FIRE_MODEL_CLASSES = {"fire", "flame"}
SMOKE_MODEL_CLASSES = {"smoke"}


def _norm(name: str) -> str:
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


class HazardDetector:
    def __init__(
        self,
        fire_ratio_warn: float = 0.012,
        fire_ratio_alert: float = 0.04,
        smoke_ratio_alert: float = 0.18,
        enable_fire_heuristic: bool = True,
        hazard_model=None,
    ):
        self.fire_ratio_warn = fire_ratio_warn
        self.fire_ratio_alert = fire_ratio_alert
        self.smoke_ratio_alert = smoke_ratio_alert
        self.enable_fire_heuristic = enable_fire_heuristic
        # 선택적 화재/연기 전용 YOLO 모델 (있으면 융합). 없으면 휴리스틱만.
        self.hazard_model = hazard_model

    # ---------- 색상 휴리스틱 ----------

    def _fire_smoke_ratio(self, frame: np.ndarray) -> Dict[str, float]:
        if cv2 is None or frame is None or frame.size == 0:
            return {"fire": 0.0, "smoke": 0.0}
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        except Exception:
            return {"fire": 0.0, "smoke": 0.0}
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        total = float(h.size) or 1.0
        # 불꽃: 적/주황 색상 + 높은 채도 + 매우 밝음
        fire_mask = (((h <= 25) | (h >= 160)) & (s >= 110) & (v >= 180))
        fire_ratio = float(np.count_nonzero(fire_mask)) / total
        # 연기: 낮은 채도(무채색) + 중간 밝기 영역이 화면에 넓게 퍼짐
        smoke_mask = ((s <= 45) & (v >= 90) & (v <= 210))
        smoke_ratio = float(np.count_nonzero(smoke_mask)) / total
        return {"fire": fire_ratio, "smoke": smoke_ratio}

    # ---------- 모델 융합 ----------

    def _model_hazards(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        if self.hazard_model is None:
            return []
        try:
            results = self.hazard_model(frame, verbose=False)
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        if not results:
            return out
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return out
        names = getattr(self.hazard_model, "names", {})
        try:
            classes = boxes.cls.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            xyxy = boxes.xyxy.cpu().numpy()
        except Exception:
            return out
        for cls, conf, box in zip(classes, confs, xyxy):
            label = _norm(names.get(int(cls), str(int(cls))))
            kind = None
            if label in {_norm(c) for c in FIRE_MODEL_CLASSES}:
                kind = "fire"
            elif label in {_norm(c) for c in SMOKE_MODEL_CLASSES}:
                kind = "smoke"
            if kind:
                out.append({
                    "type": kind,
                    "label": "화재" if kind == "fire" else "연기",
                    "confidence": float(conf),
                    "severity": "high" if kind == "fire" else "medium",
                    "source": "model",
                    "box": [float(b) for b in box],
                })
        return out

    # ---------- 탐지 기반 ----------

    def _smoking_hazards(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        smoking_set = {_norm(c) for c in SMOKING_CLASSES}
        for det in detections:
            if _norm(det.get("class", "")) in smoking_set:
                out.append({
                    "type": "smoking",
                    "label": "흡연/화기 위험",
                    "confidence": float(det.get("confidence", 0.0)),
                    "severity": "medium",
                    "source": "detection",
                    "box": det.get("box"),
                })
        return out

    def _fall_from_height_hazards(
        self, detections: List[Dict[str, Any]], frame_size: Optional[tuple]
    ) -> List[Dict[str, Any]]:
        """고소작업 추락 의심: 사람 박스가 프레임 상단에 있고 빠르게 하강할 때.

        velocity 정보가 있으면 하강 속도를, 없으면 상단 위치만 보수적으로 본다.
        """
        if not frame_size:
            return []
        _, height = frame_size
        out = []
        for det in detections:
            if det.get("class") != "person":
                continue
            box = det.get("box")
            if not box:
                continue
            top_y = box[1]
            vy = float(det.get("velocity_y", det.get("velocity", 0.0)) or 0.0)
            in_upper = top_y < 0.25 * height
            falling_fast = vy > 18.0
            if in_upper and falling_fast:
                out.append({
                    "type": "fall_from_height",
                    "label": "고소작업 추락 의심",
                    "confidence": min(1.0, vy / 40.0),
                    "severity": "high",
                    "source": "heuristic",
                    "box": box,
                })
        return out

    # ---------- 통합 ----------

    def analyze(
        self,
        frame: np.ndarray,
        detections: Optional[List[Dict[str, Any]]] = None,
        frame_size: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        detections = detections or []
        hazards: List[Dict[str, Any]] = []

        # 1) 화재/연기 색상 휴리스틱
        if self.enable_fire_heuristic:
            ratios = self._fire_smoke_ratio(frame)
            if ratios["fire"] >= self.fire_ratio_warn:
                severity = "high" if ratios["fire"] >= self.fire_ratio_alert else "low"
                hazards.append({
                    "type": "fire",
                    "label": "화재(불꽃) 의심",
                    "confidence": round(min(1.0, ratios["fire"] / self.fire_ratio_alert), 3),
                    "severity": severity,
                    "source": "heuristic_color",
                    "metric": round(ratios["fire"], 4),
                })
            if ratios["smoke"] >= self.smoke_ratio_alert:
                hazards.append({
                    "type": "smoke",
                    "label": "연기 의심",
                    "confidence": round(min(1.0, ratios["smoke"] / 0.4), 3),
                    "severity": "medium",
                    "source": "heuristic_color",
                    "metric": round(ratios["smoke"], 4),
                })

        # 2) 전용 모델 융합 (있을 때만)
        hazards.extend(self._model_hazards(frame))
        # 3) 흡연/화기
        hazards.extend(self._smoking_hazards(detections))
        # 4) 고소작업 추락
        hazards.extend(self._fall_from_height_hazards(detections, frame_size))

        # alert 승격: severity high가 하나라도 있으면 alert.
        alert = any(h.get("severity") == "high" for h in hazards)
        reasons = [h["label"] for h in hazards if h.get("severity") in ("high", "medium")]
        return {
            "hazards": hazards,
            "hazard_alert": alert,
            "hazard_reasons": reasons,
            "count": len(hazards),
        }
