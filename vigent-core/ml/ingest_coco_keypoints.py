"""COCO person keypoints → 데이터 엔진 학습 표본(실제 포즈).

지금까지 posture/fall 모델은 '합성 + 규칙' 데이터로 학습됐다. 이 스크립트는
COCO의 실제 사람 포즈(키포인트)를 특징 벡터로 변환하고 규칙 선생님으로 라벨링해
데이터 엔진에 auto 표본으로 적재한다. 그러면 retrain이 합성 대신 *실제 포즈 분포*로
재학습하여 모델이 현실에 더 강해진다.

COCO 키포인트 순서는 pose_features 의 COCO-17 과 동일하다(검증됨).

실행: ./.venv/bin/python -m backend.ml.ingest_coco_keypoints
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np

try:
    from .pose_features import extract_features
    from .bootstrap_labels import rule_label
    from .fall_model import rule_label_fall
    from ..data_engine import DataEngine
except ImportError:  # 단독/스크립트 실행
    import sys
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent))
    from pose_features import extract_features
    from bootstrap_labels import rule_label
    from fall_model import rule_label_fall
    from data_engine import DataEngine

_ROOT = Path(__file__).resolve().parent.parent.parent
ANN_VAL = _ROOT / "data" / "external" / "incoming" / "annotations" / "person_keypoints_val2017.json"
ANN_TRAIN = _ROOT / "data" / "external" / "incoming" / "annotations" / "person_keypoints_train2017.json"
DE_ROOT = _ROOT / "data" / "data_engine"

# 라벨에 핵심인 관절은 보여야 함(코·어깨·엉덩이·무릎·발목)
CORE = [0, 5, 6, 11, 12, 13, 14, 15, 16]


def _to_points(flat):
    pts, vis = [], []
    for i in range(17):
        pts.append([float(flat[3 * i]), float(flat[3 * i + 1])])
        vis.append(int(flat[3 * i + 2]))
    return pts, vis


def ingest(ann_path: Path, cap: int = 20000) -> int:
    data = json.loads(ann_path.read_text())
    de = DataEngine(root=DE_ROOT)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n = 0
    with de.training_path("posture").open("a", encoding="utf-8") as pf, \
         de.training_path("fall").open("a", encoding="utf-8") as ff:
        for ann in data.get("annotations", []):
            if ann.get("num_keypoints", 0) < 10:
                continue
            pts, vis = _to_points(ann["keypoints"])
            if any(vis[i] == 0 for i in CORE):
                continue
            # 팔(팔꿈치/손목)이 안 보이면 인접 관절로 채워 각도가 폭주하지 않게
            for e, s in ((7, 5), (8, 6)):
                if vis[e] == 0:
                    pts[e] = pts[s]
            for w, e in ((9, 7), (10, 8)):
                if vis[w] == 0:
                    pts[w] = pts[e]
            feats = extract_features(pts)
            rec_p = {"features": [float(x) for x in feats], "label": int(rule_label(feats)),
                     "status": "auto", "source": "coco", "ts": now}
            rec_f = {"features": [float(x) for x in feats], "label": int(rule_label_fall(feats)),
                     "status": "auto", "source": "coco", "ts": now}
            pf.write(json.dumps(rec_p) + "\n")
            ff.write(json.dumps(rec_f) + "\n")
            n += 1
            if n >= cap:
                break
    de_stats_p = de.training_stats("posture")
    de_stats_f = de.training_stats("fall")
    print(f"ingested {n} real poses from {ann_path.name}")
    print("posture:", de_stats_p, "| fall:", de_stats_f)
    return n


def main():
    path = ANN_VAL if ANN_VAL.exists() else ANN_TRAIN
    if not path.exists():
        raise SystemExit(f"COCO 주석이 없습니다: {path}")
    ingest(path)


if __name__ == "__main__":
    main()
