"""정확도 측정 하니스 — 라벨된 평가셋으로 클래스별 정확도(precision/recall/mAP) 자동 측정.

KISA 지능형 CCTV 인증(카테고리별 90%+)의 토대. 모델 불가지론(rf-detr 기본, 교체 가능).
전부 permissive(rfdetr Apache-2.0, supervision MIT).

사용:
  python3 vigent-core/ml/eval_accuracy.py data/retrain/office  --target person
  python3 vigent-core/ml/eval_accuracy.py data/retrain/person  --target person --limit 200
출력: runs/eval/<셋이름>_<시각>.json + 콘솔 표 + KISA 90% 게이트 판정
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import supervision as sv
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
KST_NOW = lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
KISA_GATE = 0.90


def load_yolo_gt(ds: Path, split: str, target_name: str):
    """평가셋의 정답(GT)을 supervision Detections 로 로드(타깃 클래스만)."""
    names = yaml.safe_load(open(ds / "data.yaml", encoding="utf-8"))["names"]
    if target_name not in [n.lower() for n in names]:
        raise SystemExit(f"'{target_name}' 클래스가 이 데이터셋에 없음. 가능: {names}")
    tgt_idx = [n.lower() for n in names].index(target_name)
    img_dir, lbl_dir = ds / split / "images", ds / split / "labels"
    items = []
    for img in sorted(img_dir.iterdir()):
        if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        import cv2
        im = cv2.imread(str(img))
        if im is None:
            continue
        h, w = im.shape[:2]
        boxes = []
        lbl = lbl_dir / f"{img.stem}.txt"
        if lbl.exists():
            for line in lbl.read_text().splitlines():
                p = line.split()
                if len(p) < 5 or int(p[0]) != tgt_idx:
                    continue
                cx, cy, bw, bh = map(float, p[1:5])
                boxes.append([(cx - bw / 2) * w, (cy - bh / 2) * h,
                              (cx + bw / 2) * w, (cy + bh / 2) * h])
        gt = sv.Detections(
            xyxy=np.array(boxes, dtype=float) if boxes else np.zeros((0, 4)),
            class_id=np.zeros(len(boxes), dtype=int))
        items.append((str(img), gt, (w, h)))
    return items


RFDETR_MODELS = {"nano": "RFDETRNano", "small": "RFDETRSmall",
                 "medium": "RFDETRMedium", "large": "RFDETRLarge"}   # XL/2XL 금지


def run_detector(items, target_name: str, conf: float, model_name: str = "nano"):
    """rf-detr 로 추론 → 타깃 클래스만 supervision Detections 로."""
    import rfdetr
    import torch
    from PIL import Image
    from rfdetr.util.coco_classes import COCO_CLASSES
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    cls = getattr(rfdetr, RFDETR_MODELS[model_name])
    model = cls(device=dev)
    try: model.optimize_for_inference()
    except Exception: pass
    preds, t0 = [], time.time()
    for path, _gt, _wh in items:
        det = model.predict(Image.open(path).convert("RGB"), threshold=conf)
        names = np.array([COCO_CLASSES[c] for c in det.class_id])
        sel = names == target_name
        preds.append(sv.Detections(
            xyxy=det.xyxy[sel] if sel.any() else np.zeros((0, 4)),
            confidence=det.confidence[sel] if sel.any() else np.zeros(0),
            class_id=np.zeros(int(sel.sum()), dtype=int)))
    return preds, dev, (time.time() - t0) / max(1, len(items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="YOLO 데이터셋 폴더(data.yaml 포함)")
    ap.add_argument("--split", default="valid")
    ap.add_argument("--target", default="person", help="측정할 클래스(소문자)")
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=0, help="평가 이미지 수 제한(0=전체)")
    ap.add_argument("--model", default="nano", choices=list(RFDETR_MODELS), help="rf-detr 크기")
    args = ap.parse_args()

    ds = Path(args.dataset) if Path(args.dataset).is_absolute() else ROOT / args.dataset
    items = load_yolo_gt(ds, args.split, args.target.lower())
    if args.limit:
        items = items[:args.limit]
    print(f"[eval] 데이터셋 {ds.name}/{args.split} · 타깃 '{args.target}' · {len(items)}장")

    print(f"[eval] 모델 rf-detr-{args.model}")
    preds, dev, per_img = run_detector(items, args.target.lower(), args.conf, args.model)
    gts = [gt for _p, gt, _wh in items]

    # 지표 계산(supervision)
    from supervision.metrics import F1Score, MeanAveragePrecision, Precision, Recall
    mAP = MeanAveragePrecision().update(preds, gts).compute()
    prec = Precision().update(preds, gts).compute()
    rec = Recall().update(preds, gts).compute()
    f1 = F1Score().update(preds, gts).compute()

    n_gt = sum(len(g) for g in gts)
    n_pred = sum(len(p) for p in preds)
    p50, r50, f50 = float(prec.precision_at_50), float(rec.recall_at_50), float(f1.f1_50)
    result = {
        "model": f"rf-detr-{args.model}",
        "dataset": ds.name, "split": args.split, "target": args.target,
        "images": len(items), "gt_boxes": n_gt, "pred_boxes": n_pred,
        "conf_threshold": args.conf, "device": dev,
        "ms_per_image": round(per_img * 1000, 1),
        "precision@50": round(p50, 4), "recall@50": round(r50, 4), "f1@50": round(f50, 4),
        "mAP@50": round(float(mAP.map50), 4), "mAP@50-95": round(float(mAP.map50_95), 4),
        "kisa_gate": KISA_GATE,
        "kisa_pass": bool(p50 >= KISA_GATE and r50 >= KISA_GATE),
        "measured_at": datetime.now().isoformat(timespec="seconds"),
    }

    out_dir = ROOT / "runs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{ds.name}_{args.target}_{KST_NOW()}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n────────── 정확도 측정 결과 ──────────")
    print(f"  타깃 클래스 : {args.target}  (GT {n_gt}개 / 예측 {n_pred}개)")
    print(f"  Precision@50: {p50*100:5.1f}%   (정밀도: 잡은 것 중 맞은 비율)")
    print(f"  Recall@50   : {r50*100:5.1f}%   (재현율: 실제 중 잡은 비율)")
    print(f"  F1@50       : {f50*100:5.1f}%")
    print(f"  mAP@50      : {result['mAP@50']*100:5.1f}%")
    print(f"  속도        : {result['ms_per_image']}ms/장 ({dev})")
    print(f"  ── KISA 게이트(90%) : {'✅ 통과' if result['kisa_pass'] else '❌ 미달'} "
          f"(P {p50*100:.0f}% · R {r50*100:.0f}%)")
    print(f"  저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
