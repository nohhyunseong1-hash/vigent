"""운동 자세 정확도(정/오) 분류기 — AI Hub '피트니스 자세' 사람 라벨로 학습.

posture/fall과 달리 규칙이 아니라 **사람이 라벨링한 정자세/오자세**(conditions 전부
충족=정자세)로 학습한다. 즉 약지도가 아닌 *진짜 지도학습*. AX Fitness의
"자세 점수 / 오류 피드백"에 직접 쓰인다.

pose_features의 COCO-17 특징을 그대로 사용하고, 추론은 JSON 가중치(numpy)로 한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

try:
    from .pose_features import extract_features, NUM_FEATURES
    from .posture_model import forward_json
except ImportError:  # pragma: no cover
    from pose_features import extract_features, NUM_FEATURES
    from posture_model import forward_json

FORM_CLASSES = ["incorrect", "correct"]   # 0=오자세, 1=정자세
NUM_FORM_CLASSES = len(FORM_CLASSES)
FORM_LABEL_KO = {"incorrect": "오자세", "correct": "정자세"}

# AI Hub pts 의 관절명 (COCO-17 순서와 동일)
COCO_NAMES = [
    "Nose", "Left Eye", "Right Eye", "Left Ear", "Right Ear",
    "Left Shoulder", "Right Shoulder", "Left Elbow", "Right Elbow",
    "Left Wrist", "Right Wrist", "Left Hip", "Right Hip",
    "Left Knee", "Right Knee", "Left Ankle", "Right Ankle",
]

_HERE = Path(__file__).resolve().parent
DEFAULT_FORM_WEIGHTS = _HERE.parent / "static" / "models" / "form" / "form_weights.json"

# 폼 분류는 각도(10) + 골반중심 기준 정규화 키포인트 좌표(17×2=34) = 44차원을 쓴다.
# 미세한 자세 차이를 더 잘 구분하기 위해 좌표 정보를 추가한다.
FORM_NUM_FEATURES = NUM_FEATURES + 34


def extract_form_features(keypoints: Sequence[Sequence[float]]) -> np.ndarray:
    base = extract_features(keypoints)  # 각도/기울기 10
    a = np.asarray(keypoints, dtype=np.float32)[:17, :2]
    if a.shape[0] < 17:
        a = np.vstack([a, np.zeros((17 - a.shape[0], 2), np.float32)])
    hip = (a[11] + a[12]) / 2.0
    shoulder = (a[5] + a[6]) / 2.0
    torso = float(np.linalg.norm(shoulder - hip)) or 1.0
    norm = ((a - hip) / torso).flatten().astype(np.float32)  # 34, 골반중심·몸통길이 정규화
    norm = np.clip(norm, -3.0, 3.0)
    return np.concatenate([base, norm])


def pts_to_keypoints(pts: Dict[str, Any]) -> Optional[List[List[float]]]:
    """AI Hub pts(dict) → COCO-17 [x,y] 리스트. 관절 누락 시 None."""
    out = []
    for name in COCO_NAMES:
        p = pts.get(name)
        if not p or "x" not in p or "y" not in p:
            return None
        out.append([float(p["x"]), float(p["y"])])
    return out


class FormClassifier:
    """자세 정확도 분류기. JSON 가중치(numpy) 추론. 모델 없으면 backend='none'."""

    def __init__(self, weights_json: Optional[Path] = None):
        self.weights_json = Path(weights_json) if weights_json else DEFAULT_FORM_WEIGHTS
        self.layers: Optional[List[Dict[str, Any]]] = None
        self.backend = "none"
        self.error: Optional[str] = None
        if self.weights_json.exists():
            try:
                self.layers = json.loads(self.weights_json.read_text(encoding="utf-8"))["layers"]
                self.backend = "json"
            except Exception as exc:
                self.error = str(exc)

    def capabilities(self) -> Dict[str, Any]:
        return {"backend": self.backend, "weights_json": str(self.weights_json),
                "classes": FORM_CLASSES, "error": self.error if self.backend == "none" else None}

    def predict(self, features: Sequence[float]) -> Dict[str, Any]:
        if self.layers is None:
            return {"class_name": "unknown", "confidence": 0.0, "source": "none"}
        f = np.asarray(features, dtype=np.float32).reshape(FORM_NUM_FEATURES)
        probs = forward_json(self.layers, f)
        cls = int(np.argmax(probs))
        return {"class_id": cls, "class_name": FORM_CLASSES[cls],
                "label_ko": FORM_LABEL_KO[FORM_CLASSES[cls]],
                "confidence": float(probs[cls]), "probs": [float(p) for p in probs],
                "source": "json"}

    def predict_from_keypoints(self, keypoints: Sequence[Sequence[float]]) -> Dict[str, Any]:
        return self.predict(extract_form_features(keypoints))
