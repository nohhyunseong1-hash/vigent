"""요가 동작 '인식' 학습 — 이미지 → MediaPipe 33점 → 분류기 + 브라우저용 템플릿 export.

브라우저(sports)와 동일한 정규화(어깨중심·어깨너비, BODY_IDX)로 특징을 뽑아,
학습된 '동작별 대표 템플릿'을 JSON 으로 내보낸다. 브라우저는 등록 없이 이 템플릿으로
사람의 동작을 자동 인식(최근접) → 그 동작의 정답각도로 피드백.

사용: python3 vigent-core/ml/train_yoga.py
출력: config/yoga_templates.json (브라우저 로드용) + 콘솔 정확도(하니스)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "yoga"
MODEL = ROOT / "vigent-core" / "weights" / "pose_landmarker.task"

# 브라우저 sports featureVec 와 동일한 몸 관절(얼굴·손 제외)
BODY_IDX = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
# 데이터셋 라벨 → VIGENT 동작 id (라이브러리와 매칭)
LABEL_MAP = {"chair": "chair", "cobra": "cobra", "dog": "downdog",
             "tree": "tree", "warrior": "warrior2"}


def _landmarker():
    import mediapipe as mp  # noqa: F401
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    opts = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.IMAGE)
    return vision.PoseLandmarker.create_from_options(opts)


def feature(landmarks) -> list[float] | None:
    """브라우저와 동일: 어깨중심 평행이동 + 어깨너비 스케일 정규화."""
    p = {i: landmarks[i] for i in range(len(landmarks))}
    if 11 not in p or 12 not in p:
        return None
    cx, cy = (p[11].x + p[12].x) / 2, (p[11].y + p[12].y) / 2
    s = np.hypot(p[11].x - p[12].x, p[11].y - p[12].y) or 1.0
    v = []
    for i in BODY_IDX:
        v += [(p[i].x - cx) / s, (p[i].y - cy) / s]
    return v


def extract(split: str):
    import mediapipe as mp
    lm = _landmarker()
    X, y = [], []
    base = DATA / split
    for label in sorted(os.listdir(base)):
        d = base / label
        if not d.is_dir():
            continue
        for fp in sorted(d.iterdir()):
            if fp.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            try:
                img = mp.Image.create_from_file(str(fp))
                res = lm.detect(img)
            except Exception:  # noqa: BLE001
                continue
            if not res.pose_landmarks:
                continue
            f = feature(res.pose_landmarks[0])
            if f:
                X.append(f); y.append(LABEL_MAP.get(label, label))
    return np.array(X), np.array(y)


def main():
    print("[학습] 요가 동작 인식 — MediaPipe 33점 추출 중(train)…")
    Xtr, ytr = extract("train")
    print(f"  train 특징 {len(Xtr)}개")
    print("[학습] test 추출 중…")
    Xte, yte = extract("test")
    print(f"  test 특징 {len(Xte)}개")

    # 분류기 학습 + 정확도(하니스)
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report
    clf = RandomForestClassifier(n_estimators=300, random_state=42).fit(Xtr, ytr)
    pred = clf.predict(Xte)
    acc = accuracy_score(yte, pred)
    print(f"\n── 정확도(하니스): {acc*100:.1f}% ──")
    print(classification_report(yte, pred))

    # 브라우저용 템플릿 export: 동작별 대표 벡터(과적합 방지 위해 클래스당 다수 샘플)
    templates = {}
    for cls in sorted(set(ytr)):
        vecs = Xtr[ytr == cls]
        # 대표 15개(랜덤 샘플) + 중심 1개
        idx = np.random.RandomState(42).choice(len(vecs), min(15, len(vecs)), replace=False)
        reps = [vecs[i].tolist() for i in idx]
        reps.append(vecs.mean(axis=0).tolist())
        templates[cls] = reps

    out = {"_meta": {"source": "google yoga_poses (TF tutorial)", "accuracy": round(acc, 4),
                     "feature": "MediaPipe33 BODY_IDX normalized (브라우저 동일)",
                     "classes": sorted(set(ytr))},
           "templates": templates}
    fp = ROOT / "config" / "yoga_templates.json"
    fp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ 브라우저용 템플릿 저장: {fp.relative_to(ROOT)} "
          f"({sum(len(v) for v in templates.values())}개 템플릿)")


if __name__ == "__main__":
    main()
