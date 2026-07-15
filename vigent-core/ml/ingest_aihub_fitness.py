"""AI Hub '피트니스 자세' 라벨 → form 학습 표본(정/오 자세, 사람 라벨).

conditions가 전부 True면 정자세(1), 하나라도 False면 오자세(0).
COCO-17 pts → pose_features 특징 벡터. 데이터엔진 'form' 학습파일에 status=reviewed
(사람 라벨이므로)로 적재한다.

실행: ./.venv/bin/python -m backend.ml.ingest_aihub_fitness
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

try:
    from ..data_engine import DataEngine
    from .form_model import extract_form_features, pts_to_keypoints
except ImportError:
    import sys
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
    from data_engine import DataEngine
    from form_model import extract_form_features, pts_to_keypoints

_ROOT = Path(__file__).resolve().parent.parent.parent
DE_ROOT = _ROOT / "data" / "data_engine"
CANDIDATES = [
    _ROOT / "data" / "external" / "incoming" / "aihub231",   # 정식 데이터(중첩 폴더, 재귀 탐색)
    Path.home() / "Downloads" / "013.피트니스자세_sample" / "라벨링데이터",
    _ROOT / "data" / "external" / "incoming" / "aihub_fitness" / "라벨링데이터",
]


def ingest(label_dir: Path) -> int:
    # 재귀 탐색 + 3D 파일(-3d.json, 라벨 없음) 제외
    files = sorted(str(p) for p in Path(label_dir).rglob("*.json") if not p.name.endswith("-3d.json"))
    de = DataEngine(root=DE_ROOT)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n = pos = 0
    # form 표본은 이번 ingest로 새로 구성 (overwrite)
    with de.training_path("form").open("w", encoding="utf-8") as out:
        for f in files:
            d = json.load(open(f, encoding="utf-8"))
            conds = d.get("type_info", {}).get("conditions", [])
            label = 1 if (conds and all(c.get("value") for c in conds)) else 0
            for fr in d.get("frames", []):
                for vv in fr.values():
                    kp = pts_to_keypoints(vv.get("pts", {}))
                    if kp is None:
                        continue
                    feats = extract_form_features(kp)
                    out.write(json.dumps({
                        "features": [float(x) for x in feats], "label": label,
                        "status": "reviewed", "source": "aihub", "ts": now,
                    }) + "\n")
                    n += 1
                    pos += label
    print(f"ingested {n} (정자세 {pos}, 오자세 {n-pos}) from {label_dir}")
    print("form stats:", de.training_stats("form"))
    return n


def main():
    path = next((p for p in CANDIDATES if p.exists()), None)
    if path is None:
        raise SystemExit("AI Hub 라벨 폴더를 찾지 못함: " + " | ".join(str(c) for c in CANDIDATES))
    ingest(path)


if __name__ == "__main__":
    main()
