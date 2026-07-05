"""eval_rfdetr_custom.py — 파인튜닝 RF-DETR(커스텀 클래스) 게이트 평가 (T10b).

배경: run_eval._predict_rfdetr 은 예측을 COCO_CLASSES 로 하드코딩 → COCO 사전학습 모델 전용.
파인튜닝 모델은 자체 클래스 공간(model.class_names, 예: ['forklift'])이라 COCO_CLASSES 로는 오매핑.
이 파일은 **run_eval 의 측정 로직(_load_gt·_evaluate·COCOeval·GT·CONF)을 그대로 재사용**하고,
예측을 model.class_names 로 **정확히 매핑**만 추가한다(presence_eval.py 와 동일 선례 — 측정 무수정).

산출: box mAP@50(raw, COCOeval) + presence(recall/precision/FAR, 이미지수준). 네거티브 포함 평가셋 지원.
실행: /opt/anaconda3/bin/python3 benchmarks/eval_rfdetr_custom.py --dataset forklift --weights ~/Downloads/rfdetr_forklift/checkpoint_best_total.pth
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "benchmarks"))
sys.path.insert(0, str(_ROOT / "vigent-core"))

from run_eval import _DATASETS, _gt_names, _load_gt, _evaluate, _imgs, _norm, CONF   # 측정 로직 재사용(무수정)
from presence_eval import _gt_presence, _ap_presence, _op_point, _RAW_F1_THR


def _predict(cfg, gt_names, weights):
    """커스텀 RF-DETR 예측 → (COCO detections, 이미지별 클래스 최대conf). 클래스는 model.class_names 로 매핑."""
    import cv2
    from PIL import Image
    from rfdetr import RFDETRNano
    import device as _device

    dev = _device.pick_device(prefer_mps=True)
    model = RFDETRNano(pretrain_weights=str(weights), device=dev)
    with contextlib.suppress(Exception):
        model.optimize_for_inference()
    cls_names = list(model.class_names)                    # 예: ['forklift'] (0-indexed)
    gt_cat = {_norm(n): i + 1 for i, n in enumerate(gt_names)}
    gt, id_map, img_ids = _load_gt(cfg, gt_names)

    def name_of(cid: int):
        # class_id 는 0-indexed 로 model.class_names 에 대응. 범위 밖(예: 1-class 모델의 cid=1)은
        # DETR 배경/no-object 쿼리 → 매핑하지 않고 무시(실측: cid=1이 배경, 저conf 다량 → 매핑 시 mAP 오염).
        return cls_names[cid] if 0 <= cid < len(cls_names) else None

    detections, scores = [], {}
    seen_cids = set()
    for p in _imgs(cfg):
        if p.stem not in id_map:
            continue
        img_id = id_map[p.stem][0]
        img = cv2.imread(str(p))
        if img is None:
            continue
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        det = model.predict(pil, threshold=CONF)
        xyxy = getattr(det, "xyxy", [])
        d = {}
        for j in range(len(xyxy)):
            cid = int(det.class_id[j]); seen_cids.add(cid)
            name = name_of(cid)
            catid = gt_cat.get(_norm(name)) if name else None
            if catid is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy[j])
            conf = float(det.confidence[j])
            detections.append({"image_id": img_id, "category_id": catid,
                               "bbox": [x1, y1, x2 - x1, y2 - y1], "score": conf})
            gn = gt_names[catid - 1]
            d[gn] = max(d.get(gn, 0.0), conf)
        scores[p.stem] = d
    print(f"  예측 class_id 관측: {sorted(seen_cids)} · class_names={cls_names}")
    return gt, detections, img_ids, scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=list(_DATASETS))
    ap.add_argument("--weights", required=True)
    ap.add_argument("--neg", type=int, default=0, help="네거티브 이미지 수(FAR 분모, presence 표시용)")
    args = ap.parse_args()

    cfg = _DATASETS[args.dataset]
    gt_names = _gt_names(cfg)
    gt, detections, img_ids, scores = _predict(cfg, gt_names, args.weights)

    # box mAP (COCOeval, run_eval._evaluate 재사용 = 측정 무수정)
    metrics = _evaluate(gt, detections, img_ids, gt_names)
    # presence (이미지수준)
    gtp = _gt_presence(cfg, gt_names)
    print(f"\n===== RF-DETR 커스텀 게이트: {args.dataset} =====")
    print(f"  box mAP@50 = {metrics['mAP@50']}%   mAP@50:95 = {metrics['mAP@50:95']}%")
    print(f"  클래스별 AP@50: {metrics.get('per_class_AP@50')}")
    for gn in gt_names:
        items = [(scores[st].get(gn, 0.0), 1 if gn in gtp.get(st, set()) else 0) for st in scores]
        apv, bf1, bthr = _ap_presence(items)
        op = _op_point(scores, gtp, gt_names, _RAW_F1_THR)[gn]
        fp = op["pred_pos"] - op["tp"]
        far = round(fp / args.neg * 100, 1) if args.neg else None
        print(f"  presence[{gn}]: AP={apv}%  R={op['recall']}  P={op['precision']}  "
              f"FP={fp}{f'/{args.neg}네거→FAR={far}%' if args.neg else ''}")


if __name__ == "__main__":
    main()
