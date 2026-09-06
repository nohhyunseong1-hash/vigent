#!/usr/bin/env python3
"""[P-2] person 이중 신호 앙상블 — dev셋 전용 측정.

person 슬롯 검출기와 ppe 슬롯 자체의 Person 클래스, 두 신호가 dev(74장)에서 각각 무엇을
잡고 놓치는지 먼저 재고(1단계), 이득이 있으면 OR+NMS 로 합쳐 재현율·정밀도·지연 변화를
측정한다(2단계). dev로만 채점(docs/perf_improvement_plan.md 최상단 원칙).

해상도는 명시 override 없이 guard 기본값(config/tuning.yaml detect.imgsz)을 그대로 쓴다 — 예전엔
imgsz=960을 하드코딩했으나, RF-DETR 어댑터의 dead parameter 버그로 그 값이 실제로 적용된 적이
없었다([Q-3]에서 수정, benchmarks/p3_1_resolution_ab_BLOCKED.md). [Q-3] 수정 후 하드코딩을
유지하면 재실행 시 결과가 이 문서 최초 측정과 달라진다 — 그래서 override 를 없애 항상 "현재
운용 해상도"를 자동으로 따라가게 했다. 운용 임계(person 0.40 / ppe 0.35, tuning.yaml)는 그대로.
"""
from __future__ import annotations

import json
import sys
import time
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
import env_guard  # noqa: E402
import tuning  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

IOU_MATCH = 0.50      # COCO 표준
FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]


def _iou(a: list[float], b: list[float]) -> float:
    """a,b = [x1,y1,x2,y2] (정규화 0~1)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_gt_person(stem: str) -> list[list[float]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if CLASSES[int(parts[0])] != "person":
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def _greedy_match(gts: list[list[float]], preds: list[dict[str, Any]]) -> tuple[set[int], set[int]]:
    """gt idx(hit) / pred idx(used) 집합 반환. 1:1, IoU 내림차순."""
    pairs = []
    for gi, g in enumerate(gts):
        for pi, p in enumerate(preds):
            v = _iou(g, p["bbox"])
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
    return gt_hit, pred_used


def _nms_dedup(preds: list[dict[str, Any]], iou_thresh: float = 0.5) -> list[dict[str, Any]]:
    """같은 클래스끼리 conf 내림차순 표준 NMS(소스 다른 두 신호를 합칠 때 중복 제거)."""
    kept: list[dict[str, Any]] = []
    for p in sorted(preds, key=lambda x: -x["conf"]):
        if all(_iou(p["bbox"], k["bbox"]) < iou_thresh for k in kept):
            kept.append(p)
    return kept


def main() -> None:
    env_guard.warn_if_docker_running("p2_person_ensemble")

    conf_cfg = tuning.section("detect").get("conf") or {}
    op = {"person": float(conf_cfg.get("person", 0.35)), "ppe": float(conf_cfg.get("ppe", 0.35))}
    guard = bq._build_guard()
    print(f"운용 임계: person={op['person']} ppe={op['ppe']}  imgsz={guard.IMGSZ}(guard 기본값)")
    print(f"dev 프레임: {SPLIT['n_dev']}장 (test는 안 건드림)")

    both = only_a = only_b = neither = 0
    gt_total = 0
    fp_a = fp_b = fp_union_raw = fp_union_nms = 0
    dt_a_total = dt_b_total = 0
    tp_union_nms = 0
    n_gt_union_hit = 0
    lat_a: list[float] = []
    lat_b: list[float] = []
    frame_rows: list[dict[str, Any]] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gts = _load_gt_person(stem)
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue

        t0 = time.perf_counter()
        out_a = detect_isolated(guard, img, detectors=["person"])
        lat_a.append((time.perf_counter() - t0) * 1000)
        preds_a = [d for d in out_a.get("detections", [])
                   if d.get("label") == "person" and float(d.get("conf", 0.0)) >= op["person"]]

        t0 = time.perf_counter()
        out_b = detect_isolated(guard, img, detectors=["ppe"])
        lat_b.append((time.perf_counter() - t0) * 1000)
        preds_b = [d for d in out_b.get("detections", [])
                   if d.get("label") == "person" and float(d.get("conf", 0.0)) >= op["ppe"]]

        dt_a_total += len(preds_a)
        dt_b_total += len(preds_b)

        hit_a, used_a = _greedy_match(gts, preds_a)
        hit_b, used_b = _greedy_match(gts, preds_b)
        fp_a += len(preds_a) - len(used_a)
        fp_b += len(preds_b) - len(used_b)

        n_both = len(hit_a & hit_b)
        n_only_a = len(hit_a - hit_b)
        n_only_b = len(hit_b - hit_a)
        n_neither = len(gts) - len(hit_a | hit_b)
        both += n_both
        only_a += n_only_a
        only_b += n_only_b
        neither += n_neither
        gt_total += len(gts)

        # ── 2단계: OR + NMS 앙상블 ──
        union_raw = preds_a + preds_b
        fp_union_raw += 0  # (참고용, 실제 집계는 NMS 이후로)
        union_nms = _nms_dedup(union_raw, iou_thresh=0.5)
        hit_u, used_u = _greedy_match(gts, union_nms)
        tp_union_nms += len(hit_u)
        fp_union_nms += len(union_nms) - len(used_u)
        n_gt_union_hit += len(hit_u)

        if n_only_b > 0 or n_neither > 0:
            frame_rows.append({
                "file": fname, "gt": len(gts), "only_a": n_only_a, "only_b": n_only_b,
                "both": n_both, "neither": n_neither,
            })

    print(f"\n=== 1단계: dev {SPLIT['n_dev']}장, GT person {gt_total}건 — 겹침/차집합 ===")
    print(f"  A(person 슬롯) 단독 예측 {dt_a_total}건, 오탐 {fp_a}건")
    print(f"  B(ppe 슬롯 Person) 단독 예측 {dt_b_total}건, 오탐 {fp_b}건")
    print(f"  둘 다 잡음(both)     : {both:4d} ({100*both/gt_total:.1f}%)" if gt_total else "")
    print(f"  A만 잡음(only_a)     : {only_a:4d} ({100*only_a/gt_total:.1f}%)" if gt_total else "")
    print(f"  B만 잡음(only_b)     : {only_b:4d} ({100*only_b/gt_total:.1f}%)  ← 이게 앙상블 잠재 이득" if gt_total else "")
    print(f"  둘 다 놓침(neither)  : {neither:4d} ({100*neither/gt_total:.1f}%)" if gt_total else "")
    rec_a = 100 * (both + only_a) / gt_total if gt_total else 0.0
    rec_b = 100 * (both + only_b) / gt_total if gt_total else 0.0
    prec_a = 100 * (dt_a_total - fp_a) / dt_a_total if dt_a_total else 0.0
    prec_b = 100 * (dt_b_total - fp_b) / dt_b_total if dt_b_total else 0.0
    print(f"\n  A 단독: 재현율 {rec_a:.1f}% 정밀도 {prec_a:.1f}%")
    print(f"  B 단독: 재현율 {rec_b:.1f}% 정밀도 {prec_b:.1f}%")

    print("\n=== 2단계: OR + NMS(IoU>=0.5) 앙상블 ===")
    rec_u = 100 * tp_union_nms / gt_total if gt_total else 0.0
    n_dt_u = tp_union_nms + fp_union_nms
    prec_u = 100 * tp_union_nms / n_dt_u if n_dt_u else 0.0
    print(f"  재현율 {rec_u:.1f}% (A 대비 {rec_u-rec_a:+.1f}%p) · 정밀도 {prec_u:.1f}% (A 대비 {prec_u-prec_a:+.1f}%p)")
    print(f"  TP {tp_union_nms} FP {fp_union_nms} (A는 TP {both+only_a} FP {fp_a})")

    lat_a.sort(); lat_b.sort()
    p50_a = lat_a[len(lat_a)//2] if lat_a else 0.0
    p50_b = lat_b[len(lat_b)//2] if lat_b else 0.0
    print("\n=== 지연 ===")
    print(f"  A(person 슬롯) median {p50_a:.1f}ms · B(ppe 슬롯) median {p50_b:.1f}ms")
    print(f"  둘 다 돌리면(현재 구조 그대로 순차 실행 가정) 약 {p50_a+p50_b:.1f}ms(단순 합산 — 병렬화 안 한 경우)")

    if frame_rows:
        print(f"\n=== B가 기여하거나 둘 다 놓친 프레임({len(frame_rows)}장) ===")
        for r in frame_rows:
            print(f"  {r['file']}: GT{r['gt']} both={r['both']} only_a={r['only_a']} only_b={r['only_b']} neither={r['neither']}")


if __name__ == "__main__":
    main()
