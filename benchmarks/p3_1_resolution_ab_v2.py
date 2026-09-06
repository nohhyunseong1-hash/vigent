#!/usr/bin/env python3
"""[Q-2] PPE 입력 해상도 A/B — 순차 로드 방식(다중 인스턴스 상주 없음).

[Q-3]에서 rfdetr_adapter.py의 imgsz dead-parameter 버그를 고친 뒤에야 이 실험이 의미를 가진다
(그 전엔 6조합 전부 항상 384로만 돌았다 — benchmarks/p3_1_resolution_ab_BLOCKED.md).

RF-DETR은 해상도를 **로드 시점에 컴파일 고정**한다(optimize_for_inference() 제약) — 그래서 운영처럼
해상도 1개만 상주시키는 구조를 그대로 벤치마크에도 적용한다: 해상도마다 **새 guard 인스턴스를
로드 → dev 74장 채점 → 다음 해상도로 넘어가기 전 참조 해제**(다중 인스턴스 동시 상주 안 함).

해상도 후보: 384(현재 실제 운영값, [Q-3] 발견 전까지 항상 이 값이었음) · 640 · 960(tuning.yaml
기존 표기값) · 1280(perf_improvement_plan.md 원안 후보) — 전부 RFDETRNano의 블록 크기(32) 배수라
반올림 없이 그대로 로드된다(rfdetr_adapter._RESOLUTION_BLOCK 참고).

dev로만 채점(docs/perf_improvement_plan.md 최상단 원칙).
"""
from __future__ import annotations

import gc
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
from isolated_detect import detect_isolated  # noqa: E402

RESOLUTIONS = [384, 640, 960, 1280]
ENSEMBLE_STATES = [True, False]
IOU_MATCH = 0.50
FRAMES_DIR = field_eval("frames")
LABELS_DIR = field_eval("labels")
SPLIT = json.loads((field_eval("dev_test_split.json")).read_text(encoding="utf-8"))
CLASSES = [c.strip() for c in (field_eval("classes.txt")).read_text(encoding="utf-8").splitlines() if c.strip()]


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


def run_resolution(resolution: int) -> list[dict[str, Any]]:
    """이 해상도로 guard 를 새로 로드해 앙상블 on/off 둘 다 채점 후 반환. 끝나면 호출부가 참조 해제."""
    print(f"\n[로드] resolution={resolution} guard 생성 중...")
    guard = bq._build_guard()
    guard.IMGSZ = resolution   # [Q-2] _get_model() 이 이 값을 읽어 로드 시점에 적용(Q-3 배선)
    # 첫 detect() 호출 시 지연 로드되므로, 실제 로드된 해상도를 warmup 호출로 확인한다.
    warm_img = cv2.imread(str(FRAMES_DIR / SPLIT["dev"][0]))
    detect_isolated(guard, warm_img, detectors=["person", "ppe"], imgsz=resolution)
    loaded = guard._get_model("person").resolution
    print(f"  실제 로드된 해상도: {loaded}" + ("" if loaded == resolution else f"  ★요청({resolution})과 다름(반올림됨)"))

    results = []
    for ensemble in ENSEMBLE_STATES:
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
            out = detect_isolated(guard, img, detectors=["person", "ppe"], imgsz=resolution)
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
        per_class = {c: {"rec": (r := _prf(per_class_tp[c], per_class_fp[c], per_class_gt[c]))[0],
                         "prec": r[1], "f1": r[2], "gt": per_class_gt[c],
                         "tp": per_class_tp[c], "fp": per_class_fp[c]} for c in CLASSES}
        ppe_classes = [c for c in CLASSES if c != "person"]
        ppe_tp = sum(per_class_tp[c] for c in ppe_classes)
        ppe_fp = sum(per_class_fp[c] for c in ppe_classes)
        ppe_gt = sum(per_class_gt[c] for c in ppe_classes)
        ppe_rec, ppe_prec, ppe_f1 = _prf(ppe_tp, ppe_fp, ppe_gt)
        results.append({"resolution": resolution, "loaded_resolution": loaded, "ensemble": ensemble,
                        "lat_p50": p50, "lat_p90": p90, "per_class": per_class,
                        "ppe_overall": {"rec": ppe_rec, "prec": ppe_prec, "f1": ppe_f1}})
        print(f"  ensemble={ensemble}: person rec={per_class['person']['rec']:.1f}% "
              f"prec={per_class['person']['prec']:.1f}%  lat_p50={p50:.1f}ms")

    # [해제] 다음 해상도로 넘어가기 전 이 guard(+로드된 모델)의 참조를 끊는다(다중 상주 방지).
    del guard
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return results


def main() -> None:
    env_guard.warn_if_docker_running("p3_1_resolution_ab_v2")
    print(f"dev {SPLIT['n_dev']}장, RESOLUTIONS={RESOLUTIONS}(순차 로드), ENSEMBLE_STATES={ENSEMBLE_STATES}")

    all_results: list[dict[str, Any]] = []
    for resolution in RESOLUTIONS:
        all_results.extend(run_resolution(resolution))

    print("\n=== person ===")
    print(f"{'res':>5s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'lat_p50':>9s} {'lat_p90':>9s}")
    for r in all_results:
        p = r["per_class"]["person"]
        print(f"{r['resolution']:>5d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% "
              f"{p['f1']:>6.1f}% {r['lat_p50']:>8.1f}ms {r['lat_p90']:>8.1f}ms")

    print("\n=== NO-Hardhat(★최우선 개선대상) ===")
    print(f"{'res':>5s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'GT':>4s}")
    for r in all_results:
        p = r["per_class"]["NO-Hardhat"]
        print(f"{r['resolution']:>5d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% "
              f"{p['f1']:>6.1f}% {p['gt']:>4d}")

    print("\n=== PPE 전체(6클래스 합산) ===")
    print(f"{'res':>5s} {'ensemble':>9s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s}")
    for r in all_results:
        p = r["ppe_overall"]
        print(f"{r['resolution']:>5d} {str(r['ensemble']):>9s} {p['rec']:>7.1f}% {p['prec']:>7.1f}% {p['f1']:>6.1f}%")

    out_path = _ROOT / "benchmarks" / "results" / "p3_1_resolution_ab_v2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 결과: {out_path}")


if __name__ == "__main__":
    main()
