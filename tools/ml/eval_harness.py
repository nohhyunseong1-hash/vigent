"""eval_harness.py — 객체탐지 평가 하니스 (정밀도·재현율·mAP@0.5)

깨끗하게 라벨된 평가셋(YOLO 형식)에 대해 VIGENT 탐지를 돌려 진짜 점수를 낸다.
  · 이미지마다 추적기 초기화(사진은 영상이 아님 — 누적 오탐 방지)
  · GT vs 예측을 IoU 0.5로 매칭 → TP/FP/FN → 정밀도·재현율·F1
  · 신뢰도 내림차순으로 mAP@0.5(AP) 근사 계산

사용:
  python tools/ml/eval_harness.py --set data/eval/clean --cls person
  (라벨은 YOLO: "cls cx cy w h" 정규화. --cls 는 평가할 클래스명)

⚠ 평가셋 라벨이 '완전·정확'해야 점수가 신뢰됨(라벨 누락이면 정밀도가 거짓으로 낮아짐).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "vigent-core"))


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _load_gt(lbl_path):
    boxes = []
    if not os.path.exists(lbl_path):
        return boxes
    for line in open(lbl_path):
        p = line.split()
        if len(p) >= 5:
            cx, cy, w, h = map(float, p[1:5])
            boxes.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return boxes


def evaluate(eval_dir, cls="person", iou_thr=0.5, detector_slot="person"):
    import cv2
    import main
    bundle = main.STATE.get(main.DEFAULT_THEME) or main._load_theme(main.DEFAULT_THEME)
    guard = bundle["agents"].get("Guard")

    imgs = sorted(glob.glob(os.path.join(eval_dir, "images", "*")))
    preds_all = []      # (conf, is_tp) — AP용
    n_gt = 0
    TP = FP = FN = 0
    for imgp in imgs:
        base = os.path.splitext(os.path.basename(imgp))[0]
        gts = _load_gt(os.path.join(eval_dir, "labels", base + ".txt"))
        n_gt += len(gts)
        img = cv2.imread(imgp)
        if img is None:
            continue
        guard._tracks = []      # ★ 추적기 초기화(누적 오탐 방지)
        out = guard.detect(img, detectors=[detector_slot])
        preds = sorted(
            [(d["bbox"], d["conf"]) for d in out.get("detections", [])
             if str(d["label"]).lower() == cls.lower()],
            key=lambda x: -x[1])
        matched = set()
        for bb, cf in preds:
            best, bi = -1.0, -1
            for i, g in enumerate(gts):
                if i in matched:
                    continue
                v = _iou(bb, g)
                if v > best:
                    best, bi = v, i
            is_tp = best >= iou_thr and bi >= 0
            if is_tp:
                matched.add(bi)
                TP += 1
            else:
                FP += 1
            preds_all.append((cf, is_tp))
        FN += len(gts) - len(matched)

    prec = TP / (TP + FP) if (TP + FP) else 0.0
    rec = TP / (TP + FN) if (TP + FN) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    # mAP@0.5 (AP) — 신뢰도 내림차순 누적 PR 곡선 면적(11-point 근사)
    preds_all.sort(key=lambda x: -x[0])
    tp_c = fp_c = 0
    pr_points = []
    for _, is_tp in preds_all:
        if is_tp:
            tp_c += 1
        else:
            fp_c += 1
        p = tp_c / (tp_c + fp_c)
        r = tp_c / n_gt if n_gt else 0.0
        pr_points.append((r, p))
    ap = 0.0
    for t in [i / 10 for i in range(11)]:
        ps = [p for r, p in pr_points if r >= t]
        ap += (max(ps) if ps else 0.0) / 11

    return {
        "images": len(imgs), "n_gt": n_gt, "TP": TP, "FP": FP, "FN": FN,
        "precision": round(prec * 100, 1), "recall": round(rec * 100, 1),
        "f1": round(f1 * 100, 1), "mAP50": round(ap * 100, 1),
    }


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="data/eval/clean")
    ap.add_argument("--cls", default="person")
    ap.add_argument("--iou", type=float, default=0.5)
    args = ap.parse_args()
    r = evaluate(os.path.join(_ROOT, args.set), cls=args.cls, iou_thr=args.iou)
    print("=" * 48)
    print(f"평가셋: {args.set} | 클래스: {args.cls} | IoU≥{args.iou}")
    print(f"이미지 {r['images']}장 | 정답 박스 {r['n_gt']}개")
    print(f"TP {r['TP']} | FP {r['FP']} | FN {r['FN']}")
    print(f"재현율 {r['recall']}% | 정밀도 {r['precision']}% | F1 {r['f1']} | mAP@0.5 {r['mAP50']}%")
    print("=" * 48)
    if r["images"] < 30:
        print("⚠ 표본이 작음 — 신뢰도 위해 수백 장으로 확장 필요")


if __name__ == "__main__":
    main_cli()
