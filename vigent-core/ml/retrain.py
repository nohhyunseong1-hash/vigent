"""데이터 엔진 재학습 루프.

부트스트랩(규칙 합성) + 데이터 엔진에 쌓인 실측 표본(검수=reviewed, 자동=auto)을
합쳐 모델을 재학습한다. 검수 표본은 가중치를 높여(oversample) 시간이 갈수록
규칙을 능가하도록 한다.

실행: ./.venv/bin/python -m backend.ml.retrain posture
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

import numpy as np

try:
    from .bootstrap_labels import CLASS_NAMES, NUM_CLASSES, make_dataset
    from .fall_model import DEFAULT_FALL_WEIGHTS, FALL_CLASSES, NUM_FALL_CLASSES, make_fall_dataset
    from .pose_features import FEATURE_NAMES, NUM_FEATURES
    from .train_posture_classifier import ARTIFACT as POSTURE_KERAS
    from .train_posture_classifier import TFJS_DIR as POSTURE_DIR
except ImportError:  # pragma: no cover
    from bootstrap_labels import CLASS_NAMES, NUM_CLASSES, make_dataset
    from fall_model import DEFAULT_FALL_WEIGHTS, FALL_CLASSES, NUM_FALL_CLASSES, make_fall_dataset
    from pose_features import FEATURE_NAMES, NUM_FEATURES
    from train_posture_classifier import ARTIFACT as POSTURE_KERAS
    from train_posture_classifier import TFJS_DIR as POSTURE_DIR


def assemble_training_data(bootstrap: Tuple[np.ndarray, np.ndarray],
                           reviewed_X, reviewed_y,
                           auto_X=None, auto_y=None,
                           review_weight: int = 8, auto_weight: int = 1):
    """부트스트랩 + 실측 표본 결합. 검수 표본은 review_weight배 복제(우선시)."""
    bX, by = bootstrap
    bX = np.asarray(bX, dtype=np.float32).reshape(-1, NUM_FEATURES)
    by = np.asarray(by, dtype=np.int64).reshape(-1)
    parts_X = [bX]
    parts_y = [by]
    if reviewed_X is not None and len(reviewed_X):
        rX = np.asarray(reviewed_X, dtype=np.float32).reshape(-1, NUM_FEATURES)
        ry = np.asarray(reviewed_y, dtype=np.int64).reshape(-1)
        parts_X.append(np.repeat(rX, review_weight, axis=0))
        parts_y.append(np.repeat(ry, review_weight, axis=0))
    if auto_X is not None and len(auto_X) and auto_weight > 0:
        aX = np.asarray(auto_X, dtype=np.float32).reshape(-1, NUM_FEATURES)
        ay = np.asarray(auto_y, dtype=np.int64).reshape(-1)
        parts_X.append(np.repeat(aX, auto_weight, axis=0))
        parts_y.append(np.repeat(ay, auto_weight, axis=0))
    X = np.concatenate(parts_X, axis=0)
    y = np.concatenate(parts_y, axis=0)
    idx = np.random.default_rng(0).permutation(len(X))
    return X[idx], y[idx]


def _export_json(model, class_names, out_path: Path):
    layers = []
    for layer in model.layers:
        w = layer.get_weights()
        if len(w) != 2:
            continue
        W, b = w
        layers.append({"units": int(b.shape[0]),
                       "activation": layer.get_config().get("activation", "linear"),
                       "W": W.astype(float).tolist(), "b": b.astype(float).tolist()})
    payload = {"feature_names": FEATURE_NAMES, "class_names": class_names, "layers": layers}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload), encoding="utf-8")


def retrain(model_name: str, data_engine=None, epochs: int = 30):
    import tensorflow as tf

    if model_name == "posture":
        bootstrap = make_dataset()
        class_names, num_classes = CLASS_NAMES, NUM_CLASSES
        out_json = POSTURE_DIR / "posture_weights.json"
        hidden = [32, 16]
    elif model_name == "fall":
        bootstrap = make_fall_dataset()
        class_names, num_classes = FALL_CLASSES, NUM_FALL_CLASSES
        out_json = DEFAULT_FALL_WEIGHTS
        hidden = [24, 12]
    else:
        raise ValueError(f"알 수 없는 모델: {model_name}")

    rX, ry, aX, ay = [], [], [], []
    if data_engine is not None:
        rX, ry = data_engine.load_training_samples(model_name, status="reviewed")
        aX, ay = data_engine.load_training_samples(model_name, status="auto")

    X, y = assemble_training_data(bootstrap, rX, ry, aX, ay)
    print(f"[{model_name}] train samples={len(X)} (reviewed={len(rX)}, auto={len(aX)})")

    layers = [tf.keras.layers.Input(shape=(NUM_FEATURES,))]
    for h in hidden:
        layers.append(tf.keras.layers.Dense(h, activation="relu"))
    layers.append(tf.keras.layers.Dense(num_classes, activation="softmax"))
    model = tf.keras.Sequential(layers)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(X, y, epochs=epochs, batch_size=64, verbose=2, validation_split=0.15)

    _export_json(model, class_names, out_json)
    # posture는 백엔드가 .keras도 로드하므로 함께 갱신(재학습 실제 반영)
    if model_name == "posture":
        POSTURE_KERAS.parent.mkdir(parents=True, exist_ok=True)
        model.save(POSTURE_KERAS)
    print(f"[{model_name}] re-exported -> {out_json}")
    return str(out_json)


if __name__ == "__main__":
    import sys
    retrain(sys.argv[1] if len(sys.argv) > 1 else "posture")
