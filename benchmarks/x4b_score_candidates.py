#!/usr/bin/env python3
"""[X-4b] 신규 체크포인트 3종 vs 현행 ppe_rfdetr_v1 — dev 74장 비교 채점.

지표:
  - person 재현율(전체 157건 + [X-4a] 가림 부분집합 50건 별도)
  - NO-Hardhat 재현율 구간([X-1] 방식 그대로: 하한 전체 GT 기준, 상한 ambiguous 40건 제외
    14건 기준 + Clopper-Pearson 95% CI)
  - PPE 전체(person 제외 전 클래스) 정밀도·재현율·F1

체크포인트 교체는 guard._rfdetr_weights["ppe"]를 첫 detect 호출 전에 덮어써서 수행한다
(순차 로드 — 서버 구조 변경 없음, [P-3-1]/[Q-2]와 동일 패턴). test 35장은 건드리지 않는다.
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
from data_paths import field_eval  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402
from scipy.stats import beta  # noqa: E402

FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]
PPE_CLASSES = [c for c in CLASSES if c != "person"]
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))
AMBIGUOUS = json.loads((field_eval("ambiguous_no_hardhat.json")).read_text(encoding="utf-8"))
OCCLUSION = json.loads((field_eval("person_occlusion_subset.json")).read_text(encoding="utf-8"))
IOU_MATCH = 0.50

RUN_DIR = _ROOT / "data" / "runs" / "x4_train_full_ppe_v2"
CANDIDATES: list[tuple[str, str | None]] = [
    ("현행(ppe_rfdetr_v1)", None),
    ("신규 best_ema", str(RUN_DIR / "checkpoint_best_ema.pth")),
    ("신규 best_regular", str(RUN_DIR / "checkpoint_best_regular.pth")),
    ("신규 best_total", str(RUN_DIR / "checkpoint_best_total.pth")),
]


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _bbox_key(file: str, bbox: list[float]) -> tuple:
    return (file, round(bbox[0] * 1e6), round(bbox[1] * 1e6), round(bbox[2] * 1e6), round(bbox[3] * 1e6))


def _load_gt(stem: str) -> list[tuple[str, list[float]]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        cls = CLASSES[int(parts[0])]
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append((cls, [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]))
    return out


def _match(gts: list[list[float]], preds: list[list[float]]) -> set[int]:
    pairs = []
    for gi, g in enumerate(gts):
        for pi, p in enumerate(preds):
            v = _iou(g, p)
            if v >= IOU_MATCH:
                pairs.append((v, gi, pi))
    pairs.sort(key=lambda x: -x[0])
    gt_hit: set[int] = set()
    pred_used: set[int] = set()
    for _v, gi, pi in pairs:
        if gi in gt_hit or pi in pred_used:
            continue
        gt_hit.add(gi)
        pred_used.add(pi)
    return gt_hit


def score_one(weights: str | None) -> dict[str, Any]:
    guard = bq._build_guard()
    if weights:
        guard._rfdetr_weights["ppe"] = weights

    ambiguous_keys = {_bbox_key(e["file"], e["bbox"]) for e in AMBIGUOUS["items"]}
    occlusion_keys = {_bbox_key(e["file"], e["bbox"]) for e in OCCLUSION["items"]}

    person_gt_total = 0
    person_tp_total = 0
    occlusion_tp = 0
    nh_gt_total = 0
    nh_tp_total = 0
    nh_tp_clear = 0   # non-ambiguous(14건) 중 적중
    ppe_tp = {c: 0 for c in PPE_CLASSES}
    ppe_fp = {c: 0 for c in PPE_CLASSES}
    ppe_gt = {c: 0 for c in PPE_CLASSES}

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gt_all = _load_gt(stem)
        if not gt_all:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds_all = out.get("detections", [])

        # person
        person_gts = [b for c, b in gt_all if c == "person"]
        person_preds = [d["bbox"] for d in preds_all if d.get("label") == "person"]
        hit = _match(person_gts, person_preds)
        person_gt_total += len(person_gts)
        person_tp_total += len(hit)
        for gi, g in enumerate(person_gts):
            key = _bbox_key(fname, g)
            if key in occlusion_keys and gi in hit:
                occlusion_tp += 1

        # NO-Hardhat(구간용) + PPE 전체(클래스별 매칭)
        for cls in PPE_CLASSES:
            cls_gts = [b for c, b in gt_all if c == cls]
            cls_preds = [d["bbox"] for d in preds_all if d.get("label") == cls]
            cls_hit = _match(cls_gts, cls_preds)
            ppe_gt[cls] += len(cls_gts)
            ppe_tp[cls] += len(cls_hit)
            ppe_fp[cls] += len(cls_preds) - len(cls_hit)
            if cls == "NO-Hardhat":
                nh_gt_total += len(cls_gts)
                nh_tp_total += len(cls_hit)
                for gi, g in enumerate(cls_gts):
                    key = _bbox_key(fname, g)
                    if key not in ambiguous_keys and gi in cls_hit:
                        nh_tp_clear += 1

    tp_all = sum(ppe_tp.values())
    fp_all = sum(ppe_fp.values())
    gt_all_n = sum(ppe_gt.values())
    prec = tp_all / (tp_all + fp_all) if (tp_all + fp_all) else 0.0
    rec = tp_all / gt_all_n if gt_all_n else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    nh_lower = nh_tp_total / nh_gt_total if nh_gt_total else 0.0
    clear_n = nh_gt_total - len(ambiguous_keys)
    nh_upper = nh_tp_clear / clear_n if clear_n else 0.0
    alpha = 0.05
    if not clear_n:
        ci_lower, ci_upper = float("nan"), float("nan")
    else:
        ci_lower = 0.0 if nh_tp_clear == 0 else beta.ppf(alpha / 2, nh_tp_clear, clear_n - nh_tp_clear + 1)
        ci_upper = 1.0 if nh_tp_clear == clear_n else beta.ppf(1 - alpha / 2, nh_tp_clear + 1, clear_n - nh_tp_clear)

    return {
        "person_recall_all": person_tp_total / person_gt_total if person_gt_total else 0.0,
        "person_gt_total": person_gt_total,
        "person_recall_occlusion": occlusion_tp / len(occlusion_keys) if occlusion_keys else 0.0,
        "occlusion_n": len(occlusion_keys),
        "nh_lower": nh_lower, "nh_gt_total": nh_gt_total,
        "nh_upper": nh_upper, "nh_clear_n": clear_n, "nh_tp_clear": nh_tp_clear,
        "nh_ci": (ci_lower, ci_upper),
        "ppe_precision": prec, "ppe_recall": rec, "ppe_f1": f1,
        "ppe_tp": tp_all, "ppe_fp": fp_all, "ppe_gt": gt_all_n,
    }


def main() -> None:
    results = {}
    for name, weights in CANDIDATES:
        print(f"\n채점 중: {name} ({weights or '기본'})")
        results[name] = score_one(weights)

    print("\n=== [X-4b] 비교표 (dev 74장) ===")
    header = f"{'체크포인트':22s} {'person 전체':>11s} {'person 가림':>11s} {'NO-Hardhat 구간':>26s} {'PPE 정밀도':>10s} {'PPE 재현율':>10s} {'PPE F1':>8s}"
    print(header)
    for name, _ in CANDIDATES:
        r = results[name]
        nh_str = f"[{r['nh_lower']*100:.1f}%, {r['nh_upper']*100:.0f}%(CI{r['nh_ci'][0]*100:.1f}-{r['nh_ci'][1]*100:.1f})]"
        print(f"{name:22s} {r['person_recall_all']*100:>10.1f}% {r['person_recall_occlusion']*100:>10.1f}% "
              f"{nh_str:>26s} {r['ppe_precision']*100:>9.1f}% {r['ppe_recall']*100:>9.1f}% {r['ppe_f1']*100:>7.1f}%")

    out_path = _ROOT / "benchmarks" / "results" / "x4b_score_candidates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=lambda o: float(o)), encoding="utf-8")
    print(f"\n결과 JSON: {out_path}")


if __name__ == "__main__":
    main()
