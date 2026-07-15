"""자세-위험 분류기 학습 (TensorFlow/Keras) + TF.js export.

규칙 라벨러로 만든 합성 데이터로 작은 MLP를 학습한다. 결과:
- artifacts/posture_classifier.keras  (백엔드 추론용)
- ../static/models/posture/           (TF.js, 브라우저 실시간 추론용)

실행:
  ./.venv/bin/python -m backend.ml.train_posture_classifier
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from .bootstrap_labels import CLASS_NAMES, NUM_CLASSES, make_dataset
    from .pose_features import NUM_FEATURES
except ImportError:  # 단독 실행
    from bootstrap_labels import CLASS_NAMES, NUM_CLASSES, make_dataset
    from pose_features import NUM_FEATURES

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE / "artifacts" / "posture_classifier.keras"
TFJS_DIR = HERE.parent / "static" / "models" / "posture"


def build_model(tf):
    m = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(NUM_FEATURES,)),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dropout(0.1),
        tf.keras.layers.Dense(16, activation="relu"),
        tf.keras.layers.Dense(NUM_CLASSES, activation="softmax"),
    ])
    m.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return m


def main(epochs: int = 40):
    import tensorflow as tf

    X, y = make_dataset()
    n = len(X)
    idx = np.random.default_rng(0).permutation(n)
    X, y = X[idx], y[idx]
    cut = int(n * 0.85)
    Xtr, Xval, ytr, yval = X[:cut], X[cut:], y[:cut], y[cut:]

    print(f"dataset: {n} samples, classes {CLASS_NAMES}, "
          f"dist={np.bincount(y, minlength=NUM_CLASSES).tolist()}")

    model = build_model(tf)
    model.fit(Xtr, ytr, validation_data=(Xval, yval),
              epochs=epochs, batch_size=64, verbose=2)

    loss, acc = model.evaluate(Xval, yval, verbose=0)
    print(f"\nval_accuracy={acc:.4f}  val_loss={loss:.4f}")

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    model.save(ARTIFACT)
    print(f"saved Keras model -> {ARTIFACT}")

    # 브라우저용 가중치 export (JSON). tensorflowjs 컨버터의 버전 충돌을 피하기 위해
    # 작은 MLP의 가중치를 직접 JSON으로 내보내고 브라우저는 posture-model.js로 추론한다.
    export_weights_json(model)

    return acc


def export_weights_json(model):
    """Keras MLP 가중치를 브라우저가 바로 쓰는 JSON으로 저장."""
    import json

    from .bootstrap_labels import CLASS_NAMES
    from .pose_features import FEATURE_NAMES

    layers = []
    for layer in model.layers:
        weights = layer.get_weights()
        if len(weights) != 2:
            continue  # Dropout 등 파라미터 없는 레이어 건너뜀
        W, b = weights
        cfg = layer.get_config()
        layers.append({
            "units": int(b.shape[0]),
            "activation": cfg.get("activation", "linear"),
            "W": W.astype(float).tolist(),   # shape (in_dim, units)
            "b": b.astype(float).tolist(),
        })
    payload = {
        "feature_names": FEATURE_NAMES,
        "class_names": CLASS_NAMES,
        "layers": layers,
    }
    TFJS_DIR.mkdir(parents=True, exist_ok=True)
    out = TFJS_DIR / "posture_weights.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"exported browser weights -> {out}")


if __name__ == "__main__":
    main()
