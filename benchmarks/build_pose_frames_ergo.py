"""build_pose_frames_ergo.py — 근골격(ergo) 전용 고정 프레임셋 (T10c 재측정).

ergo 패리티는 '단일 인물·상반신 명확·근접' 프레임에서만 유의미(다인·소형·암전은 매칭/신뢰도 저하).
후보(evidence JPG + runs 영상 프레임)를 yolo-pose 로 스캔해 아래 조건을 '결정적으로' 만족하는
프레임 ~20장을 benchmarks/data/pose_frames_ergo/ 에 고정한다(무작위 없음 — 면적 내림차순 상위).

선별 조건(자동):
  · 어깨(5,6)+엉덩이(11,12) 키포인트 가시(conf≥0.3) = ergo 판정 가능
  · 지배 인물 1명: 최대 인물 bbox 면적비 ≥ 0.12, 그 외 인물은 면적비 < 0.08(사실상 단일)
실행: /opt/anaconda3/bin/python3 benchmarks/build_pose_frames_ergo.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "benchmarks"))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from pose_parity import _persons_yolo   # noqa: E402  선별용(판정 아님)
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)

_OUT = _ROOT / "benchmarks" / "data" / "pose_frames_ergo"
_EXCL = _ROOT / "benchmarks" / "data" / "pose_frames_ergo_excluded"   # 다인 배제분(다인 리스크 검증용)
_N = 20
_2ND_PERSON_AREA = 0.05   # 2번째 인물이 이 면적비 이상이면 '다인'으로 배제


def _area_frac(xy, cf, wh):
    v = [xy[i] for i in range(len(xy)) if cf[i] >= 0.3]
    if len(v) < 2:
        return 0.0
    v = np.array(v)
    return float((np.ptp(v[:, 0]) * np.ptp(v[:, 1])) / (wh[0] * wh[1] + 1e-9))


def _rfdetr_person_count(img):
    """RF-DETR person 검출 수(면적비 ≥0.05 유효 박스). 선별 교차검증용."""
    global _RFD
    if "_RFD" not in globals():
        from detectors.rfdetr_adapter import RfdetrDetector
        _RFD = RfdetrDetector("", {}, set())
    h, w = img.shape[:2]
    dets = _RFD.detect(img, conf=0.35)
    n = 0
    for d in dets:
        if d["label"] != "person":
            continue
        x1, y1, x2, y2 = d["bbox"]
        if (x2 - x1) * (y2 - y1) >= _2ND_PERSON_AREA:
            n += 1
    return n


def _classify(img):
    """반환: 'ergo'(정밀 단일인물) / 'multi'(다인 — 배제·보관) / None(부적합).
    기준(사용자 Step 3): 양 백엔드 모두 정확히 1명 + 부분 인물 박스 부재."""
    h, w = img.shape[:2]
    ps = _persons_yolo(img)
    assessable = [p for p in ps if all(p[1][k] >= 0.3 for k in (5, 6, 11, 12))]   # 어깨+엉덩이
    if not assessable:
        return None, 0.0
    areas = sorted((_area_frac(xy, cf, (w, h)) for xy, cf in ps), reverse=True)
    top = max(_area_frac(xy, cf, (w, h)) for xy, cf in assessable)
    if top < 0.12:
        return None, 0.0
    yolo_multi = sum(1 for a in areas if a >= _2ND_PERSON_AREA) > 1
    rf_n = _rfdetr_person_count(img)
    if yolo_multi or rf_n != 1:           # 다인/부분 인물 → 배제(보관)
        return "multi", top
    return "ergo", top                    # 양 백엔드 정확히 1명


def _candidates():
    ev = sorted((_ROOT / "data" / "evidence").rglob("*.jpg"))
    yield from (("img", p, None) for p in ev)
    for vp in sorted(media("runs").rglob("*.mp4")):
        cap = cv2.VideoCapture(str(vp))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        for fi in range(0, total, 6):     # 6프레임 간격
            yield ("vid", vp, fi)


def main():
    ergo, multi = [], []
    for kind, src, fi in _candidates():
        if kind == "img":
            img = cv2.imread(str(src)); name = src.name
        else:
            cap = cv2.VideoCapture(str(src))
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, img = cap.read(); cap.release()
            if not ok:
                continue
            name = f"{src.stem}_{fi:03d}.jpg"
        if img is None:
            continue
        cls, s = _classify(img)
        if cls == "ergo":
            ergo.append((s, name, img))
        elif cls == "multi":
            multi.append((s, name, img))
    ergo.sort(key=lambda x: (-x[0], x[1]))       # 결정적: 면적 내림차순, 이름 tie-break
    multi.sort(key=lambda x: (-x[0], x[1]))
    for d in (_OUT, _EXCL):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.jpg"):
            old.unlink()
    for i, (s, name, img) in enumerate(ergo[:_N]):
        cv2.imwrite(str(_OUT / f"ergo_{i:02d}_{name}"), img)
    for i, (s, name, img) in enumerate(multi):     # 배제 다인 프레임 보관(다인 리스크 검증 자산)
        cv2.imwrite(str(_EXCL / f"multi_{i:02d}_{name}"), img)
    print(f"ergo(정밀 단일): {min(len(ergo), _N)}장 → {_OUT.relative_to(_ROOT)}")
    print(f"배제(다인, 보관): {len(multi)}장 → {_EXCL.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
