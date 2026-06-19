"""낙상(쓰러짐) 판단 → 학습 모델 (posture 인프라 재사용).

posture 와 동일한 패턴: 규칙=선생님(약지도) → Keras 학습 → JSON export →
numpy forward 추론(TF 불필요) → 규칙 폴백. 입력은 pose_features 특징 벡터.

낙상은 '몸통이 거의 수평'인 상태로 본다(torso_incline 매우 큼).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    from .pose_features import extract_features, FEATURE_NAMES, NUM_FEATURES
    from .posture_model import forward_json
except ImportError:  # pragma: no cover
    from pose_features import extract_features, FEATURE_NAMES, NUM_FEATURES
    from posture_model import forward_json

FALL_CLASSES = ["normal", "fall"]
NUM_FALL_CLASSES = len(FALL_CLASSES)

_TORSO = FEATURE_NAMES.index("torso_incline")  # 0.66 ≈ 60°, 1.0 = 90°(수평)

_HERE = Path(__file__).resolve().parent
DEFAULT_FALL_WEIGHTS = _HERE.parent / "static" / "models" / "fall" / "fall_weights.json"


def rule_label_fall(features: np.ndarray) -> int:
    """규칙 선생님: 몸통이 크게 기울면(수평에 가까우면) 낙상(1)."""
    return 1 if float(np.asarray(features)[_TORSO]) >= 0.66 else 0


def make_fall_dataset(n: int = 6000, seed: int = 7) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.random((n, NUM_FEATURES)).astype(np.float32)
    X[:, :8] = (0.4 + 0.6 * rng.random((n, 8))).astype(np.float32)
    # 절반 정도는 몸통을 수평 쪽으로 강하게 분포시켜 fall 클래스 확보
    down = rng.random(n) < 0.45
    X[down, _TORSO] = (0.55 + 0.45 * rng.random(down.sum())).astype(np.float32)
    y = np.array([rule_label_fall(x) for x in X], dtype=np.int64)
    return X, y


class FallClassifier:
    """낙상 분류기. JSON 가중치(numpy forward) 우선, 없으면 규칙 폴백."""

    def __init__(self, weights_json: Optional[Path] = None):
        self.weights_json = Path(weights_json) if weights_json else DEFAULT_FALL_WEIGHTS
        self.layers: Optional[List[Dict[str, Any]]] = None
        self.backend = "rule"
        self.error: Optional[str] = None
        if self.weights_json.exists():
            try:
                self.layers = json.loads(self.weights_json.read_text(encoding="utf-8"))["layers"]
                self.backend = "json"
            except Exception as exc:
                self.error = str(exc)

    def capabilities(self) -> Dict[str, Any]:
        return {"backend": self.backend, "weights_json": str(self.weights_json),
                "classes": FALL_CLASSES, "error": self.error if self.backend == "rule" else None}

    def predict(self, features: Sequence[float]) -> Dict[str, Any]:
        f = np.asarray(features, dtype=np.float32).reshape(NUM_FEATURES)
        if self.layers is not None:
            try:
                probs = forward_json(self.layers, f)
                cls = int(np.argmax(probs))
                return {"class_id": cls, "class_name": FALL_CLASSES[cls],
                        "confidence": float(probs[cls]), "probs": [float(p) for p in probs],
                        "source": "json"}
            except Exception:
                pass
        cls = rule_label_fall(f)
        return {"class_id": cls, "class_name": FALL_CLASSES[cls],
                "confidence": 1.0, "probs": None, "source": "rule"}

    def predict_from_keypoints(self, keypoints: Sequence[Sequence[float]]) -> Dict[str, Any]:
        return self.predict(extract_features(keypoints))
