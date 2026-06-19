"""자세 정확도(정/오) 분류기 학습 — AI Hub 사람 라벨(데이터엔진 form 표본).

불균형(정자세 소수)을 class_weight로 보정. JSON 가중치로 export.
실행: ./.venv/bin/python -m backend.ml.train_form_classifier
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    from .pose_features import FEATURE_NAMES
    from .form_model import FORM_CLASSES, NUM_FORM_CLASSES, DEFAULT_FORM_WEIGHTS, FORM_NUM_FEATURES
    from ..data_engine import DataEngine
except ImportError:
    import sys
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
    from pose_features import FEATURE_NAMES
    from form_model import FORM_CLASSES, NUM_FORM_CLASSES, DEFAULT_FORM_WEIGHTS, FORM_NUM_FEATURES
    from data_engine import DataEngine

_ROOT = Path(__file__).resolve().parent.parent.parent


def main(epochs: int = 40):
    import tensorflow as tf

    de = DataEngine(root=_ROOT / "data" / "data_engine")
    X, y = de.load_training_samples("form", status="reviewed")
    if not X:
        raise SystemExit("form 표본 없음 → 먼저 ingest_aihub_fitness 실행")
    X = np.asarray(X, dtype=np.float32); y = np.asarray(y, dtype=np.int64)
    idx = np.random.default_rng(0).permutation(len(X)); X, y = X[idx], y[idx]
    cut = int(len(X) * 0.85)
    Xtr, Xval, ytr, yval = X[:cut], X[cut:], y[:cut], y[cut:]
    dist = np.bincount(y, minlength=NUM_FORM_CLASSES)
    print(f"form 표본 {len(X)} (오자세 {dist[0]}, 정자세 {dist[1]})")

    # 클래스 가중치(불균형 보정)
    total = len(y)
    cw = {i: total / (NUM_FORM_CLASSES * max(1, dist[i])) for i in range(NUM_FORM_CLASSES)}
    print("class_weight:", {k: round(v, 2) for k, v in cw.items()})

    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(FORM_NUM_FEATURES,)),
        tf.keras.layers.Dense(64, activation="relu"),
        tf.keras.layers.Dropout(0.2),
        tf.keras.layers.Dense(32, activation="relu"),
        tf.keras.layers.Dense(NUM_FORM_CLASSES, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(Xtr, ytr, validation_data=(Xval, yval), epochs=epochs, batch_size=64,
              class_weight=cw, verbose=2)
    loss, acc = model.evaluate(Xval, yval, verbose=0)
    # 정자세 재현율(정자세를 정자세로 맞추는 비율)
    pred = np.argmax(model.predict(Xval, verbose=0), axis=1)
    pos = yval == 1
    rec_pos = float((pred[pos] == 1).mean()) if pos.any() else 0.0
    print(f"\nval_accuracy={acc:.4f} | 정자세 recall={rec_pos:.3f}")

    layers = []
    for layer in model.layers:
        w = layer.get_weights()
        if len(w) != 2:
            continue
        W, b = w
        layers.append({"units": int(b.shape[0]),
                       "activation": layer.get_config().get("activation", "linear"),
                       "W": W.astype(float).tolist(), "b": b.astype(float).tolist()})
    feat_names = list(FEATURE_NAMES) + [f"kp{i//2}_{'xy'[i%2]}" for i in range(34)]
    payload = {"feature_names": feat_names, "class_names": FORM_CLASSES, "layers": layers}
    DEFAULT_FORM_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_FORM_WEIGHTS.write_text(json.dumps(payload), encoding="utf-8")
    print("exported ->", DEFAULT_FORM_WEIGHTS)
    return acc


if __name__ == "__main__":
    main()
