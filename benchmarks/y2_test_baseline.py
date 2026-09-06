#!/usr/bin/env python3
"""[Y-2] test 35장 1회 개봉 채점 — v1 기준선(현행 ppe_rfdetr_v1, 운영 경로).

★[P-0] 원칙: test는 이 스크립트로 단 1회만 채점한다. 결과가 dev와 달라도 이 스크립트나
설정을 그 결과를 보고 다시 고치지 않는다(재조정 금지) — 차이는 그대로 보고하고 해석만 붙인다.

방법론은 dev에서 이미 쓴 것과 동일하게 맞춘다(`benchmarks/x1_no_hardhat_interval.py`,
`benchmarks/x4b_score_candidates.py`) — person/PPE는 클래스별 IoU≥0.5 매칭, NO-Hardhat은
구간(하한=전체 GT, 상한=ambiguous 제외) + Clopper-Pearson 95% CI.

★dev와의 방법론 차이(규칙7 명시): dev의 ambiguous 40건은 [X-0] 사람 육안 판정(V-0 판정
시트)으로 확정한 것이다. test에 대해 같은 판정 세션을 새로 여는 것은 "test 1회 채점"
원칙에 어긋난다(판정 자체가 test를 들여다보는 추가 실험이 됨). 대신 [S-1]이 이미 dev에서
확립한 **객관적 크기 기준**(놓친 NO-Hardhat은 100%가 소형<1%였다는 실측 사실)을 그대로
재적용해, test에서 소형(<1%)으로 놓친 건을 "ambiguous 후보"로 취급한다 — 사람 판정이 아닌
크기 프록시이므로 dev의 ambiguous 정의와 완전히 동일하지는 않다.
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
from isolated_detect import detect_isolated  # noqa: E402
from scipy.stats import beta  # noqa: E402

FRAMES_DIR = media("field_eval") / "frames"
LABELS_DIR = media("field_eval") / "labels"
CLASSES = [c.strip() for c in (media("field_eval") / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
PPE_CLASSES = [c for c in CLASSES if c != "person"]
SPLIT = json.loads((media("field_eval") / "dev_test_split.json").read_text(encoding="utf-8"))
AMBIGUOUS_DEV = json.loads((media("field_eval") / "ambiguous_no_hardhat.json").read_text(encoding="utf-8"))
IOU_MATCH = 0.50
SMALL_AREA = 0.01   # [S-1]과 동일 기준(소형<1% 프레임 면적)


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


def _prf(tp: int, fp: int, gt: int) -> tuple[float, float, float]:
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / gt if gt else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1


def score_split(split_name: str, ambiguous_keys: set | None) -> dict[str, Any]:
    """ambiguous_keys=None 이면 크기 기준(<1%, 놓친 것)으로 그때그때 판정(test 경로)."""
    guard = bq._build_guard()

    person_tp = person_fp = person_gt = 0
    nh_gt_total = 0
    nh_tp_total = 0
    nh_ambiguous_seen = 0
    nh_tp_clear = 0
    ppe_tp = {c: 0 for c in PPE_CLASSES}
    ppe_fp = {c: 0 for c in PPE_CLASSES}
    ppe_gt = {c: 0 for c in PPE_CLASSES}

    for fname in SPLIT[split_name]:
        stem = Path(fname).stem
        gt_all = _load_gt(stem)
        if not gt_all:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        h, w = img.shape[:2]
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds_all = out.get("detections", [])

        person_gts = [b for c, b in gt_all if c == "person"]
        person_preds = [d["bbox"] for d in preds_all if d.get("label") == "person"]
        hit = _match(person_gts, person_preds)
        person_gt += len(person_gts)
        person_tp += len(hit)
        person_fp += len(person_preds) - len(hit)

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
                    if ambiguous_keys is not None:
                        is_ambiguous = _bbox_key(fname, g) in ambiguous_keys
                    else:
                        # test 경로: 놓친 것 중 소형(<1%)이면 ambiguous 후보([S-1] 기준 재적용)
                        area = max(0.0, g[2] - g[0]) * max(0.0, g[3] - g[1])
                        is_ambiguous = (gi not in cls_hit) and area < SMALL_AREA
                    if is_ambiguous:
                        nh_ambiguous_seen += 1
                    elif gi in cls_hit:
                        nh_tp_clear += 1

    p_prec, p_rec, p_f1 = _prf(person_tp, person_fp, person_gt)
    tp_all = sum(ppe_tp.values())
    fp_all = sum(ppe_fp.values())
    gt_all_n = sum(ppe_gt.values())
    ppe_prec, ppe_rec, ppe_f1 = _prf(tp_all, fp_all, gt_all_n)

    nh_lower = nh_tp_total / nh_gt_total if nh_gt_total else 0.0
    clear_n = nh_gt_total - nh_ambiguous_seen
    nh_upper = nh_tp_clear / clear_n if clear_n else 0.0
    alpha = 0.05
    if not clear_n:
        ci = (float("nan"), float("nan"))
    else:
        lo = 0.0 if nh_tp_clear == 0 else beta.ppf(alpha / 2, nh_tp_clear, clear_n - nh_tp_clear + 1)
        hi = 1.0 if nh_tp_clear == clear_n else beta.ppf(1 - alpha / 2, nh_tp_clear + 1, clear_n - nh_tp_clear)
        ci = (lo, hi)

    return {
        "n_images": len(SPLIT[split_name]),
        "person_precision": p_prec, "person_recall": p_rec, "person_f1": p_f1,
        "person_tp": person_tp, "person_fp": person_fp, "person_gt": person_gt,
        "ppe_precision": ppe_prec, "ppe_recall": ppe_rec, "ppe_f1": ppe_f1,
        "ppe_tp": tp_all, "ppe_fp": fp_all, "ppe_gt": gt_all_n,
        "nh_lower": nh_lower, "nh_gt_total": nh_gt_total, "nh_tp_total": nh_tp_total,
        "nh_upper": nh_upper, "nh_clear_n": clear_n, "nh_tp_clear": nh_tp_clear,
        "nh_ambiguous_n": nh_ambiguous_seen, "nh_ci": ci,
    }


def main() -> None:
    ambiguous_keys_dev = {_bbox_key(e["file"], e["bbox"]) for e in AMBIGUOUS_DEV["items"]}

    print("dev 채점 중(재확인 — 기존 [X-1] 수치와 동일해야 함)...")
    dev_result = score_split("dev", ambiguous_keys_dev)

    print("\n★test 35장 1회 개봉 채점 중 — 이 실행 이후 test 결과로 설정을 재조정하지 않는다...")
    test_result = score_split("test", None)   # 크기 기준 프록시

    print("\n=== [Y-2] dev/test 비교표 (v1 기준선, 현행 ppe_rfdetr_v1) ===")
    for name, r in [("dev(74)", dev_result), ("test(35)", test_result)]:
        nh_str = f"[{r['nh_lower']*100:.1f}%, {r['nh_upper']*100:.1f}%(CI {r['nh_ci'][0]*100:.1f}-{r['nh_ci'][1]*100:.1f})]"
        print(f"\n{name}:")
        print(f"  person  P={r['person_precision']*100:.1f}% R={r['person_recall']*100:.1f}% F1={r['person_f1']*100:.1f}% (TP={r['person_tp']} FP={r['person_fp']} GT={r['person_gt']})")
        print(f"  PPE전체 P={r['ppe_precision']*100:.1f}% R={r['ppe_recall']*100:.1f}% F1={r['ppe_f1']*100:.1f}% (TP={r['ppe_tp']} FP={r['ppe_fp']} GT={r['ppe_gt']})")
        print(f"  NO-Hardhat 구간: {nh_str} (ambiguous {r['nh_ambiguous_n']}/{r['nh_gt_total']})")

    out_path = _ROOT / "benchmarks" / "results" / "y2_test_baseline.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"dev": dev_result, "test": test_result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 JSON: {out_path}")


if __name__ == "__main__":
    main()
