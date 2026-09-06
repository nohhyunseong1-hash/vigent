#!/usr/bin/env python3
"""[P-2 구현] 채택 전 확인1 — 하류 오탐 영향(dev 74장, PERSON_ENSEMBLE=True 기본값 기준).

정밀도 -9.8%p 로 늘어난 가짜 person 박스가, PPE 교차게이트(_cross_validate_ppe)를 거쳐
"미착용"(NO-Hardhat/NO-Safety-Vest/NO-Mask) 경보로 이어지는 빈도를 잰다.

측정 대상: detect(detectors=[person,ppe], PERSON_ENSEMBLE=True — 실제 채택 시 배포될 기본값)의
"미착용" 클래스 박스 각각에 대해:
  - 그 박스 자체가 GT 와 매칭되는 진짜(TP)인지 아닌지
  - cross_validate_ppe 가 참조했을 근처 person 박스(겹침 또는 15% 확장 내) 중에
    GT person 과 매칭되는 "진짜 사람"이 하나라도 있는지, 아니면 전부 가짜(FP) person 뿐인지
"완전 유령"(미착용 박스 자체도 FP 이고, 근처 person 도 전부 FP) 건수가 핵심 지표다.

해상도는 guard 기본값(config/tuning.yaml detect.imgsz)을 그대로 쓴다(명시 override 없음) —
예전엔 imgsz=960을 하드코딩했으나 RF-DETR 어댑터 dead parameter 버그로 실제 미적용이었다
([Q-3]에서 수정, benchmarks/p3_1_resolution_ab_BLOCKED.md). 재실행 시 이 문서 최초 측정과
어긋나지 않도록 override 를 제거했다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
import env_guard  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

IOU_MATCH = 0.50
FRAMES_DIR = media("field_eval") / "frames"
LABELS_DIR = media("field_eval") / "labels"
SPLIT = json.loads((media("field_eval") / "dev_test_split.json").read_text(encoding="utf-8"))
CLASSES = [c.strip() for c in (media("field_eval") / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
MISSING_LABELS = {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"}
EXPAND = 0.15  # guard.PPE_PERSON_EXPAND 기본값과 동일(cross_validate_ppe 재현)


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _near(ppe_box: list[float], person_box: list[float]) -> bool:
    """cross_validate_ppe 와 동일한 결부 조건(겹침 또는 15% 확장 영역 내 중심)."""
    cx = (ppe_box[0] + ppe_box[2]) / 2
    cy = (ppe_box[1] + ppe_box[3]) / 2
    pw = person_box[2] - person_box[0]
    ph = person_box[3] - person_box[1]
    ew, eh = pw * EXPAND, ph * EXPAND
    if _iou(ppe_box, person_box) > 0:
        return True
    return (person_box[0] - ew <= cx <= person_box[2] + ew
            and person_box[1] - eh <= cy <= person_box[3] + eh)


def _load_gt(stem: str) -> dict[str, list[list[float]]]:
    txt = LABELS_DIR / f"{stem}.txt"
    out: dict[str, list[list[float]]] = {}
    if not txt.exists():
        return out
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        cls = CLASSES[int(parts[0])]
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.setdefault(cls, []).append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def _match_flags(preds: list[dict[str, Any]], gts: list[list[float]]) -> list[bool]:
    """preds 와 같은 길이의 bool 리스트 — 각 pred 가 GT 와 매칭돼 TP 인지."""
    pairs = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            v = _iou(p["bbox"], g)
            if v >= IOU_MATCH:
                pairs.append((v, pi, gi))
    pairs.sort(key=lambda x: -x[0])
    pred_tp = [False] * len(preds)
    gt_used: set[int] = set()
    for _v, pi, gi in pairs:
        if pred_tp[pi] or gi in gt_used:
            continue
        pred_tp[pi] = True
        gt_used.add(gi)
    return pred_tp


def main() -> None:
    env_guard.warn_if_docker_running("p2_downstream_fp_check")
    guard = bq._build_guard()
    guard.PERSON_ENSEMBLE = True  # 채택 시 배포될 기본값 그대로 확인

    total_missing = 0
    fp_missing = 0
    ghost = 0            # 미착용 박스 자체도 FP + 근처 person 전부 FP
    fp_but_real_person = 0  # 미착용 박스는 FP 지만 근처에 진짜 person 있음(오탐이지만 유령person 탓은 아님)
    examples: list[str] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gt = _load_gt(stem)
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        dets = out.get("detections", [])

        persons = [d for d in dets if str(d.get("label", "")).lower() == "person"]
        gt_person = gt.get("person", [])
        person_tp_flags = _match_flags(persons, gt_person)

        for cls in MISSING_LABELS:
            preds = [d for d in dets if d.get("label") == cls]
            if not preds:
                continue
            gts = gt.get(cls, [])
            tp_flags = _match_flags(preds, gts)
            for d, is_tp in zip(preds, tp_flags):
                total_missing += 1
                if is_tp:
                    continue
                fp_missing += 1
                near_real = any(person_tp_flags[i] for i, p in enumerate(persons) if _near(d["bbox"], p["bbox"]))
                near_any = any(_near(d["bbox"], p["bbox"]) for p in persons)
                if near_real:
                    fp_but_real_person += 1
                elif near_any:
                    ghost += 1
                    if len(examples) < 10:
                        examples.append(f"{fname}: {cls} conf={d.get('conf', 0):.2f} (근처 person 전부 가짜)")
                # near_any 도 False 인 경우는 cross_validate_ppe 를 통과 못 했어야 정상(방어적 카운트 생략)

    print(f"dev {SPLIT['n_dev']}장, PERSON_ENSEMBLE=True(채택 시 기본값) 기준")
    print(f"미착용(NO-Hardhat/NO-Safety-Vest/NO-Mask) 총 검출: {total_missing}건")
    print(f"  그중 오탐(FP, GT 불일치): {fp_missing}건")
    print(f"    - 근처에 '진짜'(GT매칭) person 있음(오탐이지만 유령person 탓 아님): {fp_but_real_person}건")
    print(f"    - ★근처 person 전부 가짜(완전 유령 미착용 경보): {ghost}건")
    if examples:
        print("\n유령 경보 예시:")
        for e in examples:
            print(f"  {e}")


if __name__ == "__main__":
    main()
