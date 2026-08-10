#!/usr/bin/env python3
"""[R-1] 사람 크롭 2단계 PPE — dev 74장 A/B (오프라인 벤치 전용, 서버 미변경).

배경: [Q-2]에서 해상도를 올릴수록 PPE 재현율이 나빠졌다 — 이 체크포인트가 384 부근에서
파인튜닝된 것으로 보이는 상태에서, 전체 프레임을 384로 리사이즈하면 작은 사람의 PPE가 더
작아진다. 크롭 2단계는 같은 384 모델을 바꾸지 않고, **person 박스 주변만 잘라 그 크롭을
384로 넣어** PPE 객체가 상대적으로 커 보이게 만든다(같은 원리를 역이용).

파이프라인(오프라인, guard.py/worker.py 무수정):
  1. 전체 프레임 detect(person+ppe, 앙상블 포함) → person 박스들 + 1단계 PPE 박스.
  2. person 박스마다 여백(기본 20%, 15~25% 범위)을 두고 크롭 → 그 크롭을 다시
     detect(person+ppe)에 통과 → PPE 박스만 추출 → 좌표를 원본 프레임 좌표로 역변환(2단계).
  3. 1단계 ∪ 2단계 를 같은 클래스끼리 NMS(IoU>=0.5, conf 높은 쪽 유지)로 병합.

3조합을 dev 74장에서 채점: {1단계만(현행), 2단계만(크롭 전용), 1+2단계 병합}.
근거리/원거리(frames_manifest.json size_bucket) 별로도 나눠, 이득이 가설대로 원거리에
집중되는지 확인한다. 정밀도 하락(부작용)도 함께 센다.
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

CROP_MARGIN = 0.20     # 여백 20%(15~25% 범위 내 중간값, 사용자 지시)
IOU_MATCH = 0.50        # GT 매칭(COCO 표준)
IOU_MERGE = 0.50        # 1단계/2단계 병합 dedup 임계
FRAMES_DIR = _ROOT / "data" / "field_eval" / "frames"
LABELS_DIR = _ROOT / "data" / "field_eval" / "labels"
MANIFEST = json.loads((_ROOT / "data" / "field_eval" / "frames_manifest.json").read_text(encoding="utf-8"))
BUCKET_BY_FILE = {m["file"]: m["size_bucket"] for m in MANIFEST}
SPLIT = json.loads((_ROOT / "data" / "field_eval" / "dev_test_split.json").read_text(encoding="utf-8"))
CLASSES = [c.strip() for c in (_ROOT / "data" / "field_eval" / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
PPE_CLASSES = [c for c in CLASSES if c != "person"]


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


def _nms_merge(preds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 클래스끼리 conf 내림차순 표준 NMS(1단계/2단계 소스 무관하게 겹치면 conf 높은 쪽만)."""
    kept: list[dict[str, Any]] = []
    for p in sorted(preds, key=lambda x: -x["conf"]):
        if all(not (k["label"] == p["label"] and _iou(k["bbox"], p["bbox"]) >= IOU_MERGE) for k in kept):
            kept.append(p)
    return kept


def _crop_region(person_bbox: list[float], w: int, h: int) -> tuple[int, int, int, int]:
    """person_bbox(정규화 0~1) 에 여백을 두고 원본 픽셀 좌표 크롭 영역(x1,y1,x2,y2) 계산."""
    x1, y1, x2, y2 = person_bbox
    pw, ph = x2 - x1, y2 - y1
    ex1 = max(0.0, x1 - pw * CROP_MARGIN)
    ey1 = max(0.0, y1 - ph * CROP_MARGIN)
    ex2 = min(1.0, x2 + pw * CROP_MARGIN)
    ey2 = min(1.0, y2 + ph * CROP_MARGIN)
    return int(ex1 * w), int(ey1 * h), int(ex2 * w), int(ey2 * h)


def _transform_to_full(local_bbox: list[float], crop_px: tuple[int, int, int, int], w: int, h: int) -> list[float]:
    """크롭 내부 정규화 좌표 → 원본 프레임 정규화 좌표."""
    cx1, cy1, cx2, cy2 = crop_px
    cw, ch = cx2 - cx1, cy2 - cy1
    lx1, ly1, lx2, ly2 = local_bbox
    return [(cx1 + lx1 * cw) / w, (cy1 + ly1 * ch) / h,
            (cx1 + lx2 * cw) / w, (cy1 + ly2 * ch) / h]


def process_frame(guard: Any, fname: str) -> dict[str, Any]:
    stem = Path(fname).stem
    gt = _load_gt(stem)
    img = cv2.imread(str(FRAMES_DIR / fname))
    h, w = img.shape[:2]

    t0 = time.perf_counter()
    out_full = detect_isolated(guard, img, detectors=["person", "ppe"])
    t_stage1 = (time.perf_counter() - t0) * 1000
    dets_full = out_full.get("detections", [])
    person_boxes = [d for d in dets_full if d.get("label") == "person"]
    ppe_stage1 = [d for d in dets_full if d.get("label") in PPE_CLASSES]

    ppe_stage2: list[dict[str, Any]] = []
    t_stage2 = 0.0
    n_crops = len(person_boxes)
    for pbox in person_boxes:
        cx1, cy1, cx2, cy2 = _crop_region(pbox["bbox"], w, h)
        if cx2 - cx1 < 4 or cy2 - cy1 < 4:
            continue
        crop_img = img[cy1:cy2, cx1:cx2]
        t0 = time.perf_counter()
        out_crop = detect_isolated(guard, crop_img, detectors=["person", "ppe"])
        t_stage2 += (time.perf_counter() - t0) * 1000
        for d in out_crop.get("detections", []):
            if d.get("label") not in PPE_CLASSES:
                continue
            full_bbox = _transform_to_full(d["bbox"], (cx1, cy1, cx2, cy2), w, h)
            ppe_stage2.append({**d, "bbox": full_bbox, "source": "crop"})

    merged = _nms_merge(ppe_stage1 + ppe_stage2)

    bucket = BUCKET_BY_FILE.get(fname, "?")
    return {
        "file": fname, "bucket": bucket, "gt": gt,
        "stage1": ppe_stage1, "stage2": ppe_stage2, "merged": merged,
        "n_crops": n_crops, "lat_stage1": t_stage1, "lat_stage2": t_stage2,
    }


def _score(rows: list[dict[str, Any]], key: str, bucket_filter: str | None = None) -> dict[str, Any]:
    per_class_tp: dict[str, int] = {c: 0 for c in PPE_CLASSES}
    per_class_fp: dict[str, int] = {c: 0 for c in PPE_CLASSES}
    per_class_gt: dict[str, int] = {c: 0 for c in PPE_CLASSES}
    for r in rows:
        if bucket_filter and r["bucket"] != bucket_filter:
            continue
        preds = r[key]
        for cls in PPE_CLASSES:
            cls_preds = [d for d in preds if d.get("label") == cls]
            gts = r["gt"].get(cls, [])
            tp, fp = _greedy_match(gts, cls_preds)
            per_class_tp[cls] += tp
            per_class_fp[cls] += fp
            per_class_gt[cls] += len(gts)
    tp_all = sum(per_class_tp.values())
    fp_all = sum(per_class_fp.values())
    gt_all = sum(per_class_gt.values())
    rec, prec, f1 = _prf(tp_all, fp_all, gt_all)
    nh_rec, nh_prec, nh_f1 = _prf(per_class_tp["NO-Hardhat"], per_class_fp["NO-Hardhat"], per_class_gt["NO-Hardhat"])
    return {"rec": rec, "prec": prec, "f1": f1, "tp": tp_all, "fp": fp_all, "gt": gt_all,
            "nh_rec": nh_rec, "nh_prec": nh_prec, "nh_f1": nh_f1, "nh_gt": per_class_gt["NO-Hardhat"]}


def main() -> None:
    env_guard.warn_if_docker_running("r1_person_crop_ppe")
    print(f"dev {SPLIT['n_dev']}장, crop_margin={CROP_MARGIN}")
    guard = bq._build_guard()
    print(f"guard.IMGSZ={guard.IMGSZ} (모든 추론이 이 해상도로 내부 리사이즈됨 — 크롭 효과의 핵심)")

    rows = []
    total_lat1 = total_lat2 = 0.0
    total_crops = 0
    for i, fname in enumerate(SPLIT["dev"]):
        r = process_frame(guard, fname)
        rows.append(r)
        total_lat1 += r["lat_stage1"]
        total_lat2 += r["lat_stage2"]
        total_crops += r["n_crops"]
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(SPLIT['dev'])} 처리...")

    n = len(rows)
    print(f"\n프레임당 평균 크롭(추가 추론) 횟수: {total_crops / n:.2f}")
    print(f"1단계 지연 합계 평균: {total_lat1 / n:.1f}ms/프레임")
    print(f"2단계 지연 합계 평균: {total_lat2 / n:.1f}ms/프레임(크롭 수만큼 누적)")
    print(f"1+2단계 지연 합계 평균: {(total_lat1 + total_lat2) / n:.1f}ms/프레임")

    print("\n=== 3조합 — PPE 전체 ===")
    print(f"{'조합':10s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'TP':>5s} {'FP':>5s} {'GT':>5s}")
    for label, key in [("1단계(현행)", "stage1"), ("2단계(크롭)", "stage2"), ("1+2 병합", "merged")]:
        s = _score(rows, key)
        print(f"{label:10s} {s['rec']:>7.1f}% {s['prec']:>7.1f}% {s['f1']:>6.1f}% {s['tp']:>5d} {s['fp']:>5d} {s['gt']:>5d}")

    print("\n=== 3조합 — NO-Hardhat ===")
    print(f"{'조합':10s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'GT':>5s}")
    for label, key in [("1단계(현행)", "stage1"), ("2단계(크롭)", "stage2"), ("1+2 병합", "merged")]:
        s = _score(rows, key)
        print(f"{label:10s} {s['nh_rec']:>7.1f}% {s['nh_prec']:>7.1f}% {s['nh_f1']:>6.1f}% {s['nh_gt']:>5d}")

    print("\n=== 크기별 분해 (PPE 전체) — 이득이 원거리에 집중되는지 확인 ===")
    for bucket in ("근거리", "원거리"):
        print(f"\n-- {bucket} --")
        print(f"{'조합':10s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'GT':>5s}")
        for label, key in [("1단계(현행)", "stage1"), ("2단계(크롭)", "stage2"), ("1+2 병합", "merged")]:
            s = _score(rows, key, bucket_filter=bucket)
            print(f"{label:10s} {s['rec']:>7.1f}% {s['prec']:>7.1f}% {s['f1']:>6.1f}% {s['gt']:>5d}")

    print("\n=== 크기별 분해 (NO-Hardhat) ===")
    for bucket in ("근거리", "원거리"):
        print(f"\n-- {bucket} --")
        print(f"{'조합':10s} {'재현율':>8s} {'정밀도':>8s} {'F1':>7s} {'GT':>5s}")
        for label, key in [("1단계(현행)", "stage1"), ("2단계(크롭)", "stage2"), ("1+2 병합", "merged")]:
            s = _score(rows, key, bucket_filter=bucket)
            print(f"{label:10s} {s['nh_rec']:>7.1f}% {s['nh_prec']:>7.1f}% {s['nh_f1']:>6.1f}% {s['nh_gt']:>5d}")

    out_path = _ROOT / "benchmarks" / "results" / "r1_person_crop_ppe.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dump = [{"file": r["file"], "bucket": r["bucket"], "n_crops": r["n_crops"],
            "lat_stage1": r["lat_stage1"], "lat_stage2": r["lat_stage2"],
            "stage1": r["stage1"], "stage2": r["stage2"], "merged": r["merged"]} for r in rows]
    out_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 결과: {out_path}")


if __name__ == "__main__":
    main()
