"""정답 각도 데이터 보정 — 데이터셋의 실제 자세에서 각도를 측정해 '추정값→데이터값' 교체.

각 동작(의자·코브라·다운독·나무·전사)의 train 이미지에서 정의된 관절각도를 모두 측정,
중앙값=정답(ideal), 분포(사분위범위 기반)=허용오차(tol) 로 산출해 yoga_asanas.json 갱신.
oneOf(좌/우) 각도는 한 자세 안에서 더 그럴듯한 쪽(목표에 가까운 쪽)을 채택.

사용: python3 vigent-core/ml/calibrate_angles.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "yoga" / "train"
MODEL = ROOT / "vigent-core" / "weights" / "pose_landmarker.task"
LIB = ROOT / "config" / "yoga_asanas.json"

# 데이터셋 폴더 → VIGENT 동작 id
FOLDER2ID = {"chair": "chair", "cobra": "cobra", "dog": "downdog",
             "tree": "tree", "warrior": "warrior2"}


def angle(a, b, c):
    """관절 b 의 각도(a-b-c). 점은 (x,y)."""
    v1 = math.atan2(a[1] - b[1], a[0] - b[0])
    v2 = math.atan2(c[1] - b[1], c[0] - b[0])
    d = abs(v1 - v2) * 180 / math.pi
    return 360 - d if d > 180 else d


def landmarker():
    import mediapipe as mp  # noqa: F401
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    opts = vision.PoseLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.IMAGE)
    return vision.PoseLandmarker.create_from_options(opts)


def measure_folder(lm, folder: str, angle_specs: list[dict]):
    """동작 폴더의 모든 이미지에서 각 angle_spec 의 각도 분포를 모은다."""
    import mediapipe as mp
    d = DATA / folder
    samples = {i: [] for i in range(len(angle_specs))}
    for fp in sorted(d.iterdir()):
        if fp.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        try:
            res = lm.detect(mp.Image.create_from_file(str(fp)))
        except Exception:  # noqa: BLE001
            continue
        if not res.pose_landmarks:
            continue
        P = res.pose_landmarks[0]
        pts = {i: (P[i].x, P[i].y) for i in range(len(P))}
        vis = {i: (P[i].visibility if P[i].visibility is not None else 1) for i in range(len(P))}
        for si, spec in enumerate(angle_specs):
            cands = spec.get("oneOf", [spec["pts"]])
            best = None
            for tri in cands:
                if all(vis.get(j, 0) >= 0.3 for j in tri):
                    a = angle(pts[tri[0]], pts[tri[1]], pts[tri[2]])
                    # oneOf 면 기존 ideal 에 가까운 쪽 채택
                    if best is None or abs(a - spec["ideal"]) < abs(best - spec["ideal"]):
                        best = a
            if best is not None:
                samples[si].append(best)
    return samples


def main():
    lib = json.loads(LIB.read_text(encoding="utf-8"))
    id2asana = {a["id"]: a for a in lib["asanas"]}
    lm = landmarker()

    print("[보정] 데이터에서 실제 각도 측정 → 정답각도 교체\n")
    updated = 0
    for folder, aid in FOLDER2ID.items():
        asana = id2asana.get(aid)
        if not asana or not asana.get("angles"):
            continue
        samples = measure_folder(lm, folder, asana["angles"])
        print(f"■ {asana['name']} ({folder})")
        for si, spec in enumerate(asana["angles"]):
            arr = np.array(samples[si])
            if len(arr) < 20:
                print(f"   - {spec['name']}: 표본 부족({len(arr)}) → 추정값 유지 "
                      f"{spec['ideal']}±{spec['tol']}")
                continue
            ideal = float(np.median(arr))
            # 허용오차 = 사분위범위(IQR) 기반(이상치에 강함), 최소 10°
            q1, q3 = np.percentile(arr, [25, 75])
            tol = max(10.0, float((q3 - q1)))
            old = (spec["ideal"], spec["tol"])
            spec["ideal"] = round(ideal)
            spec["tol"] = round(tol)
            spec["data_based"] = True
            spec["n"] = int(len(arr))
            updated += 1
            print(f"   - {spec['name']}: {old[0]}±{old[1]}(추정) → "
                  f"{spec['ideal']}±{spec['tol']}(데이터 {len(arr)}장)")
        print()

    lib["_meta"]["보정"] = "5개 동작(의자·코브라·다운독·나무·전사) 정답각도를 데이터 train 셋 실측으로 교체"
    LIB.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {updated}개 각도를 데이터 기반으로 교체 → {LIB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
