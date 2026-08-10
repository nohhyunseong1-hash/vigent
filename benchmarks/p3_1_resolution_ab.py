#!/usr/bin/env python3
"""[P-3-1] PPE 입력 해상도 A/B — dev 74장 전용, {640,960,1280} x {앙상블 on,off}.

★★★ 차단됨(2026-08-10) — 실행 전 benchmarks/p3_1_resolution_ab_BLOCKED.md 먼저 읽을 것.
이 스크립트 자체는 imgsz 를 정상적으로 detect_isolated 에 넘기지만, 그 아래
vigent-core/detectors/rfdetr_adapter.py 가 imgsz 를 실제 모델 호출에 안 써서(dead parameter)
현재는 6개 조합 전부 항상 384(RFDETRNano 기본 해상도, optimize_for_inference() 로 컴파일
시점에 고정됨)로만 돈다 — 조합 간 차이가 안 나오는 게 정상이다(버그, 해상도가 진짜로 무관한
게 아님). 어댑터 수정 여부는 별도 결정 필요(BLOCKED.md §"해상도를 바꾸려면 뭐가 필요한가").

person·PPE 7클래스 전부의 재현율·정밀도·F1 + 지연(median)을 조합별로 잰다. NO-Hardhat 은
별도로 강조 표기(perf_improvement_plan.md §0: 놓친 53건 중 conf=0.10 초안에도 없던 게 0건 —
해상도가 유일하게 닿을 수 있는 지렛대인지 확인하는 게 목적).

dev로만 채점(docs/perf_improvement_plan.md 최상단 원칙). GPU(cu130) 기준 측정 — 지연 수치는
docs/benchmark_measurement_hygiene.md 절차(Docker 종료) 준수 여부를 함께 보고한다.
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
import env_guard  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

IMGSZS = [640, 960, 1280]
ENSEMBLE_STATES = [True, False]
IOU_MATCH = 0.50
FRAMES_DIR = _ROOT / "data" / "field_eval" / "frames"
LABELS_DIR = _ROOT / "data" / "field_eval" / "labels"
SPLIT = json.loads((_ROOT / "data" / "field_eval" / "dev_test_split.json").read_text(encoding="utf-8"))
CLASSES = [c.strip() for c in (_ROOT / "data" / "field_eval" / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


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


def _greedy_match(gts: list[list[float]], preds: list[dict[str, Any]]) -> tuple[int, int]:
    """(tp, fp) 반환. 1:1, IoU 내림차순."""
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
    return len(gt_hit), len(preds) - len(pred_used)


def _prf(tp: int, fp: int, n_gt: int) -> tuple[float, float, float]:
    rec = 100 * tp / n_gt if n_gt else 0.0
    prec = 100 * tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return rec, prec, f1


def run_combo(guard: Any, imgsz: int, ensemble: bool) -> dict[str, Any]:
    guard.PERSON_ENSEMBLE = ensemble
    per_class_tp: dict[str, int] = {c: 0 for c in CLASSES}
    per_class_fp: dict[str, int] = {c: 0 for c in CLASSES}
    per_class_gt: dict[str, int] = {c: 0 for c in CLASSES}
    lat: list[float] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gt = _load_gt(stem)
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        t0 = time.perf_counter()
        out = detect_isolated(guard, img, detectors=["person", "ppe"], imgsz=imgsz)
        lat.append((time.perf_counter() - t0) * 1000)
        dets = out.get("detections", [])
        for cls in CLASSES:
            preds = [d for d in dets if d.get("label") == cls]
            gts = gt.get(cls, [])
            tp, fp = _greedy_match(gts, preds)
            per_class_tp[cls] += tp
            per_class_fp[cls] += fp
            per_class_gt[cls] += len(gts)

    lat.sort()
    p50 = lat[len(lat) // 2] if lat else 0.0
    p90 = lat[int(len(lat) * 0.9)] if lat else 0.0

    per_class: dict[str, Any] = {}
    for cls in CLASSES:
        rec, prec, f1 = _prf(per_class_tp[cls], per_class_fp[cls], per_class_gt[cls])
        per_class[cls] = {"rec": rec, "prec": prec, "f1": f1, "gt": per_class_gt[cls],
                          "tp": per_class_tp[cls], "fp": per_class_fp[cls]}

    ppe_classes = [c for c in CLASSES if c != "person"]
    ppe_tp = sum(per_class_tp[c] for c in ppe_classes)
    ppe_fp = sum(per_class_fp[c] for c in ppe_classes)
    ppe_gt = sum(per_class_gt[c] for c in ppe_classes)
    ppe_rec, ppe_prec, ppe_f1 = _prf(ppe_tp, ppe_fp, ppe_gt)

    return {"imgsz": imgsz, "ensemble": ensemble, "lat_p50": p50, "lat_p90": p90,
            "per_class": per_class, "ppe_overall": {"rec": ppe_rec, "prec": ppe_prec, "f1": ppe_f1}}


def main() -> None:
    env_guard.warn_if_docker_running("p3_1_resolution_ab")
    print(f"dev {SPLIT['n_dev']}장, IMGSZS={IMGSZS}, ENSEMBLE_STATES={ENSEMBLE_STATES}")
    guard = bq._build_guard()

    results = []
    for imgsz in IMGSZS:
        for ensemble in ENSEMBLE_STATES:
            print(f"  측정 중: imgsz={imgsz} ensemble={ensemble} ...")
            r = run_combo(guard, imgsz, ensemble)
            results.append(r)

    print("\n=== person ===")
    print(f"{'imgsz':>6s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'lat_p50':>9s} {'lat_p90':>9s}")
    for r in results:
        p = r["per_class"]["person"]
        print(f"{r['imgsz']:>6d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% "
              f"{p['f1']:>6.1f}% {r['lat_p50']:>8.1f}ms {r['lat_p90']:>8.1f}ms")

    print("\n=== NO-Hardhat(★최우선 개선대상) ===")
    print(f"{'imgsz':>6s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'GT':>4s}")
    for r in results:
        p = r["per_class"]["NO-Hardhat"]
        print(f"{r['imgsz']:>6d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% "
              f"{p['f1']:>6.1f}% {p['gt']:>4d}")

    print("\n=== PPE 전체(6클래스 합산) ===")
    print(f"{'imgsz':>6s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s}")
    for r in results:
        p = r["ppe_overall"]
        print(f"{r['imgsz']:>6d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% {p['f1']:>6.1f}%")

    print("\n=== 클래스별 상세(참고) ===")
    for r in results:
        print(f"\n-- imgsz={r['imgsz']} ensemble={r['ensemble']} --")
        for cls in CLASSES:
            p = r["per_class"][cls]
            if p["gt"] == 0 and p["tp"] == 0 and p["fp"] == 0:
                continue
            print(f"  {cls:16s} 재현율={p['rec']:5.1f}% 정밀도={p['prec']:5.1f}% "
                  f"TP={p['tp']:3d} FP={p['fp']:3d} GT={p['gt']:3d}")

    out_path = _ROOT / "benchmarks" / "results" / "p3_1_resolution_ab.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 결과: {out_path}")


if __name__ == "__main__":
    main()
