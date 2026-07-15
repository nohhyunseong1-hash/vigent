"""낙상 분류기 학습 (Keras) + JSON export. posture 패턴과 동일.

실행: ./.venv/bin/python -m backend.ml.train_fall_classifier
"""
from __future__ import annotations

import json

import numpy as np

try:
    from .fall_model import DEFAULT_FALL_WEIGHTS, FALL_CLASSES, NUM_FALL_CLASSES, make_fall_dataset
    from .pose_features import FEATURE_NAMES, NUM_FEATURES
except ImportError:
    from fall_model import DEFAULT_FALL_WEIGHTS, FALL_CLASSES, NUM_FALL_CLASSES, make_fall_dataset
    from pose_features import FEATURE_NAMES, NUM_FEATURES


def main(epochs: int = 30):
    import tensorflow as tf

    X, y = make_fall_dataset()
    n = len(X)
    idx = np.random.default_rng(0).permutation(n)
    X, y = X[idx], y[idx]
    cut = int(n * 0.85)
    Xtr, Xval, ytr, yval = X[:cut], X[cut:], y[:cut], y[cut:]
    print(f"fall dataset: {n}, dist={np.bincount(y, minlength=NUM_FALL_CLASSES).tolist()}")

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(NUM_FEATURES,)),
        tf.keras.layers.Dense(24, activation="relu"),
        tf.keras.layers.Dense(12, activation="relu"),
        tf.keras.layers.Dense(NUM_FALL_CLASSES, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(Xtr, ytr, validation_data=(Xval, yval), epochs=epochs, batch_size=64, verbose=2)
    loss, acc = model.evaluate(Xval, yval, verbose=0)
    print(f"\nfall val_accuracy={acc:.4f}")

    layers = []
    for layer in model.layers:
        w = layer.get_weights()
        if len(w) != 2:
            continue
        W, b = w
        layers.append({"units": int(b.shape[0]),
                       "activation": layer.get_config().get("activation", "linear"),
                       "W": W.astype(float).tolist(), "b": b.astype(float).tolist()})
    payload = {"feature_names": FEATURE_NAMES, "class_names": FALL_CLASSES, "layers": layers}
    DEFAULT_FALL_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_FALL_WEIGHTS.write_text(json.dumps(payload), encoding="utf-8")
    print(f"exported -> {DEFAULT_FALL_WEIGHTS}")
    return acc


if __name__ == "__main__":
    main()
