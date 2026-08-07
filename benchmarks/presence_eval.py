"""presence_eval.py — 이미지수준 존재 감지 지표 (T13a, 이중 지표 체계).

배경: 박스 mAP(COCOeval)는 '검출 품질' 지표이나, 화재/연기는 현행 boda 모델이 '대영역 1박스'로
검출하고 D-Fire GT는 '소형 화염 다수 + 연기 분리'로 주석 → 스키마 불일치로 mAP가 능력을 반영 못 함.
안전 경보의 실제 용도는 "프레임에 화재/연기 있음?"이므로 **이미지수준 presence**를 병행 측정한다.
COCOeval 측정 로직(run_eval)은 무수정 — 이 파일은 지표를 '추가'만 한다(용도 정합화, 게이트 회피 아님).

정의:
  · positive 이미지 = 해당 클래스 GT 박스 ≥1.
  · 검출 = 모델이 해당 클래스 박스를 conf 임계 이상으로 ≥1개 출력.
  · 이미지 점수 = 해당 클래스 예측 박스의 최대 conf(없으면 0).
산출(클래스별): presence AP(임계무관, PR곡선 면적) + 운용점 recall/precision/F1.
  · raw: model.predict(conf 0.001) → 전체 conf 스윕 PR/AP + 기준임계 F1.
  · pipeline: guard.detect(배포 임계) → 단일 운용점 recall/precision/F1.

실행:
  /opt/anaconda3/bin/python3 benchmarks/presence_eval.py --mode raw --dataset fire_smoke --weights vigent-core/weights/fire_smoke_boda.pt
  /opt/anaconda3/bin/python3 benchmarks/presence_eval.py --mode pipeline --dataset fire_smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "benchmarks"))
sys.path.insert(0, str(_ROOT / "vigent-core"))

from run_eval import _DATASETS, _gt_names, _imgs, _norm, CONF, _OUT   # noqa: E402  측정자산 재사용

_RAW_F1_THR = 0.25   # raw presence F1 보고용 기준 임계(참고). AP 는 임계무관 주지표.


def _gt_presence(cfg, gt_names):
    """이미지 stem → 존재하는 클래스명 집합(YOLO 라벨 기준, gt_names index=class id)."""
    labels = cfg["labels"]
    out = {}
    for ip in _imgs(cfg):
        classes = set()
        lp = labels / (ip.stem + ".txt")
        if lp.exists():
            for line in lp.read_text().splitlines():
                if line.strip():
                    cid = int(line.split()[0])
                    if 0 <= cid < len(gt_names):
                        classes.add(gt_names[cid])
        out[ip.stem] = classes
    return out


def _scores_raw(weights, cfg, gt_names):
    """이미지 stem → {클래스명: 최대conf}. model.predict conf=0.001."""
    from ultralytics import YOLO
    m = YOLO(weights)
    norm2gt = {_norm(g): g for g in gt_names}
    out = {}
    for ip in _imgs(cfg):
        r = m.predict(str(ip), verbose=False, conf=CONF)[0]
        d = {}
        for b in r.boxes:
            gn = norm2gt.get(_norm(m.names[int(b.cls[0])]))
            if gn:
                d[gn] = max(d.get(gn, 0.0), float(b.conf[0]))
        out[ip.stem] = d
    return out


def _scores_pipeline(cfg, gt_names):
    """이미지 stem → {클래스명: 최대conf}. guard.detect(배포 운용점)."""
    import cv2
    import main as M
    from isolated_detect import detect_isolated
    b = M.STATE.get(M.DEFAULT_THEME) or M._load_theme(M.DEFAULT_THEME)
    g = b["agents"]["Guard"]
    slot = cfg["slot"]
    norm2gt = {_norm(x): x for x in gt_names}
    out = {}
    for ip in _imgs(cfg):
        img = cv2.imread(str(ip))
        # 2026-08: 구 `g._tracks = []`는 실제로 존재하지 않는 속성이라 죽은 코드였다(진짜 상태는
        #   `_tracks_by_key`) — 서로 무관한 GT 이미지 사이에 트랙이 안 비워진 채 새던 버그(실측 확인,
        #   benchmarks/extract_eval_frames.py와 동일 유형). detect_isolated()로 교체.
        res = detect_isolated(g, img, detectors=[slot])
        d = {}
        for det in res.get("detections", []):
            gn = norm2gt.get(_norm(det["label"]))
            if gn:
                d[gn] = max(d.get(gn, 0.0), float(det["conf"]))
        out[ip.stem] = d
    return out


def _ap_presence(items):
    """items: [(score, label01)] → image-level average precision(PR 면적) + 최적 F1·그 임계."""
    items = sorted(items, key=lambda x: -x[0])
    P = sum(l for _, l in items)
    if P == 0:
        return None, None, None
    tp = fp = 0
    ap = 0.0
    prev_r = 0.0
    best_f1 = best_thr = 0.0
    for s, l in items:
        tp += l
        fp += (1 - l)
        prec = tp / (tp + fp)
        rec = tp / P
        ap += (rec - prev_r) * prec
        prev_r = rec
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        if f1 > best_f1:
            best_f1, best_thr = f1, s
    return round(ap * 100, 2), round(best_f1 * 100, 2), round(best_thr, 3)


def _op_point(scores, gt, gt_names, thr):
    """단일 운용점 recall/precision/F1(클래스별). thr 이상 = 검출."""
    res = {}
    for gn in gt_names:
        P = sum(1 for s in gt.values() if gn in s)               # GT positive 이미지 수
        pred_pos = tp = 0
        for stem, sc in scores.items():
            det = sc.get(gn, 0.0) >= thr
            pos = gn in gt.get(stem, set())
            pred_pos += det
            tp += det and pos
        rec = tp / P if P else None
        prec = tp / pred_pos if pred_pos else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else 0.0
        res[gn] = {"gt_pos": P, "pred_pos": pred_pos, "tp": tp,
                   "recall": round(rec * 100, 2) if rec is not None else None,
                   "precision": round(prec * 100, 2) if prec is not None else None,
                   "f1": round(f1 * 100, 2)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["raw", "pipeline"], default="raw")
    ap.add_argument("--dataset", required=True, choices=list(_DATASETS))
    ap.add_argument("--weights", default="")
    args = ap.parse_args()
    if args.mode == "raw" and not args.weights:
        ap.error("--mode raw 에는 --weights 필요")

    cfg = _DATASETS[args.dataset]
    gt_names = _gt_names(cfg)
    gt = _gt_presence(cfg, gt_names)
    scores = _scores_raw(args.weights, cfg, gt_names) if args.mode == "raw" \
        else _scores_pipeline(cfg, gt_names)

    per_class = {}
    for gn in gt_names:
        items = [(scores[st].get(gn, 0.0), 1 if gn in gt.get(st, set()) else 0) for st in scores]
        apv, bf1, bthr = _ap_presence(items)
        per_class[gn] = {"presence_AP": apv, "best_f1": bf1, "best_f1_thr": bthr}
    # 운용점: raw 는 기준임계(_RAW_F1_THR), pipeline 은 guard 가 이미 임계 → 검출유무(thr>0의 최소)
    op_thr = _RAW_F1_THR if args.mode == "raw" else 1e-6
    op = _op_point(scores, gt, gt_names, op_thr)

    record = {
        "mode": args.mode, "metric": "image-level presence",
        "images": len(gt), "op_threshold": op_thr,
        "per_class_AP": per_class,
        "operating_point": op,
    }
    allres = json.loads(_OUT.read_text(encoding="utf-8")) if _OUT.exists() else {}
    allres.setdefault(args.dataset, {}).setdefault("presence", {})[args.mode] = record
    _OUT.write_text(json.dumps(allres, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== presence: {args.dataset} / {args.mode} ({len(gt)}장) =====")
    for gn in gt_names:
        a = per_class[gn]; o = op[gn]
        print(f"  {gn:8} AP={a['presence_AP']}%  bestF1={a['best_f1']}%@{a['best_f1_thr']}  "
              f"| 운용점 R={o['recall']} P={o['precision']} F1={o['f1']} (GT+ {o['gt_pos']})")
    print(f"  → 저장: {_OUT.relative_to(_ROOT)}  [{args.dataset}][presence][{args.mode}]")


if __name__ == "__main__":
    main()
