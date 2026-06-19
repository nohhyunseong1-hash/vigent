"""학습된 자세-위험 분류기 추론 래퍼 (3단 폴백, 저하 없음).

추론 백엔드 우선순위:
1. "tf"   : TensorFlow로 .keras 모델 로드 (정밀)
2. "json" : posture_weights.json 을 numpy로 forward (TF 불필요)
3. "rule" : 규칙 기반 (모델/TF 모두 없을 때)

→ TF가 없어도 JSON 가중치만 있으면 학습 모델로 추론하고, 그것조차 없으면
규칙으로 폴백하므로 서비스는 항상 기존 수준 이상으로 동작한다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

try:
    from .pose_features import extract_features, NUM_FEATURES
    from .bootstrap_labels import rule_label, CLASS_NAMES
except ImportError:  # pragma: no cover
    from pose_features import extract_features, NUM_FEATURES
    from bootstrap_labels import rule_label, CLASS_NAMES

_HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = _HERE / "artifacts" / "posture_classifier.keras"
DEFAULT_WEIGHTS_JSON = _HERE.parent / "static" / "models" / "posture" / "posture_weights.json"


def forward_json(layers: List[Dict[str, Any]], x: np.ndarray) -> np.ndarray:
    """JSON 가중치로 MLP forward (브라우저 posture-model.js와 동일 연산)."""
    a = np.asarray(x, dtype=np.float32).reshape(-1)
    for layer in layers:
        W = np.asarray(layer["W"], dtype=np.float32)   # (in, units)
        b = np.asarray(layer["b"], dtype=np.float32)
        z = a @ W + b
        act = layer.get("activation", "linear")
        if act == "relu":
            a = np.maximum(0.0, z)
        elif act == "softmax":
            e = np.exp(z - np.max(z))
            a = e / np.sum(e)
        else:
            a = z
    return a


class PostureClassifier:
    def __init__(self, model_path: Optional[Path] = None, weights_json: Optional[Path] = None):
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.weights_json = Path(weights_json) if weights_json else DEFAULT_WEIGHTS_JSON
        self.model = None
        self.json_layers: Optional[List[Dict[str, Any]]] = None
        self.backend = "rule"
        self.error: Optional[str] = None
        self._try_load()

    def _try_load(self) -> None:
        # 1) TensorFlow keras
        if self.model_path.exists():
            try:
                import tensorflow as tf
                self.model = tf.keras.models.load_model(self.model_path)
                self.backend = "tf"
                return
            except Exception as exc:
                self.error = f"tf load failed: {exc}"
        # 2) JSON 가중치 (numpy, TF 불필요)
        if self.weights_json.exists():
            try:
                data = json.loads(self.weights_json.read_text(encoding="utf-8"))
                self.json_layers = data["layers"]
                self.backend = "json"
                return
            except Exception as exc:
                self.error = f"json load failed: {exc}"
        # 3) 규칙 폴백
        self.backend = "rule"

    def capabilities(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "model_path": str(self.model_path),
            "weights_json": str(self.weights_json),
            "classes": CLASS_NAMES,
            "error": self.error if self.backend == "rule" else None,
        }

    def predict(self, features: Sequence[float]) -> Dict[str, Any]:
        f = np.asarray(features, dtype=np.float32).reshape(NUM_FEATURES)
        if self.backend == "tf" and self.model is not None:
            try:
                probs = self.model.predict(f.reshape(1, NUM_FEATURES), verbose=0)[0]
                return self._result(probs, "tf")
            except Exception:
                pass
        if self.backend == "json" and self.json_layers is not None:
            try:
                probs = forward_json(self.json_layers, f)
                return self._result(probs, "json")
            except Exception:
                pass
        cls = rule_label(f)
        return {"class_id": cls, "class_name": CLASS_NAMES[cls],
                "confidence": 1.0, "probs": None, "source": "rule"}

    def _result(self, probs: np.ndarray, source: str) -> Dict[str, Any]:
        cls = int(np.argmax(probs))
        return {
            "class_id": cls,
            "class_name": CLASS_NAMES[cls],
            "confidence": float(probs[cls]),
            "probs": [float(p) for p in probs],
            "source": source,
        }

    def predict_from_keypoints(self, keypoints: Sequence[Sequence[float]]) -> Dict[str, Any]:
        return self.predict(extract_features(keypoints))
