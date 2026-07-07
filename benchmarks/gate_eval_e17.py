"""gate_eval_e17.py — epoch-17 조기 게이트 판정.

목적: 완주(30ep) 전 현 체크포인트가 게이트를 넘는지 공식 자로 판정.
  · 게이트 B: box mAP@50 (COCOeval, run_eval._evaluate 재사용)
  · 게이트 A: presence conf 스윕 → 운용점 후보표(recall/precision/FAR, T14-F 형식)
측정/판정 로직 무수정 — 이 파일은 기존 측정함수(_predict·_evaluate·_op_point)를 '조합·보고'만 한다.

실행:
  /opt/anaconda3/bin/python3 benchmarks/gate_eval_e17.py --dataset fire_smoke \
    --weights ~/Downloads/fire_e17/checkpoint_best_ema.pth \
    --baseline vigent-core/weights/fire_smoke_boda.pt \
    --gate-map 60 --base-recall fire=53.6,smoke=24.9
  # ppe:
  /opt/anaconda3/bin/python3 benchmarks/gate_eval_e17.py --dataset ppe \
    --weights ~/Downloads/ppe_e17/checkpoint_best_ema.pth --gate-map 73.2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "benchmarks"))
sys.path.insert(0, str(_ROOT / "vigent-core"))

from run_eval import _DATASETS, _gt_names, _evaluate            # box mAP 측정(무수정)
from presence_eval import _gt_presence, _op_point, _scores_raw  # presence 측정(무수정)
from eval_rfdetr_custom import _predict                          # 커스텀 RF-DETR 예측(무수정)

SWEEP = [round(0.05 * i, 2) for i in range(1, 19)]   # 0.05 .. 0.90


def _far_table(scores, gtp, gt_names):
    """conf 스윕 → 각 임계에서 클래스별 recall/precision/FP/FAR. FAR = FP / (해당 클래스 GT 없는 이미지 수)."""
    neg = {gn: sum(1 for st in scores if gn not in gtp.get(st, set())) for gn in gt_names}
    rows = []
    for thr in SWEEP:
        op = _op_point(scores, gtp, gt_names, thr)
        row = {"thr": thr}
        for gn in gt_names:
            o = op[gn]
            fp = o["pred_pos"] - o["tp"]
            row[gn] = {"R": o["recall"], "P": o["precision"], "FP": fp,
                       "FAR": round(fp / neg[gn] * 100, 1) if neg[gn] else None}
        rows.append(row)
    return rows, neg


def _print_sweep(title, rows, gt_names):
    print(f"\n{title}")
    print("  thr  " + "".join(f"|  {gn:5} R/P/FAR       " for gn in gt_names))
    for r in rows:
        line = f"  {r['thr']:.2f} "
        for gn in gt_names:
            c = r[gn]
            line += f"| {c['R']}/{c['P']}/{c['FAR']}   "
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=list(_DATASETS))
    ap.add_argument("--weights", required=True, help="신 RF-DETR 체크포인트(.pth)")
    ap.add_argument("--baseline", default="", help="비교용 YOLO 베이스라인(.pt) — presence 스윕")
    ap.add_argument("--gate-map", type=float, default=None, help="게이트 B: box mAP@50 기준(%)")
    ap.add_argument("--base-recall", default="", help="게이트 A 기준 recall, 예: fire=53.6,smoke=24.9")
    a = ap.parse_args()

    cfg = _DATASETS[a.dataset]
    gt_names = _gt_names(cfg)
    gt, det, img_ids, scores = _predict(cfg, gt_names, a.weights)

    # ── 게이트 B: box mAP@50 ──
    m = _evaluate(gt, det, img_ids, gt_names)
    print(f"\n===== 게이트 판정: {a.dataset} · 신 RF-DETR ({Path(a.weights).name}) =====")
    print(f"[게이트 B] box mAP@50 = {m['mAP@50']}%   (mAP@50:95 = {m['mAP@50:95']}%)")
    print(f"           클래스별 AP@50 = {m.get('per_class_AP@50')}")
    if a.gate_map is not None:
        ok = m["mAP@50"] >= a.gate_map
        print(f"           → {'통과 ✅' if ok else '미달 ❌'} (기준 ≥ {a.gate_map}%)")

    # ── 게이트 A: presence conf 스윕 ──
    gtp = _gt_presence(cfg, gt_names)
    rows, neg = _far_table(scores, gtp, gt_names)
    _print_sweep(f"[게이트 A] presence conf 스윕 — 신 모델 (neg/클래스: {neg})", rows, gt_names)

    brows = None
    if a.baseline:
        bscores = _scores_raw(a.baseline, cfg, gt_names)
        brows, bneg = _far_table(bscores, gtp, gt_names)
        _print_sweep(f"[비교] 베이스라인 {Path(a.baseline).name} presence 스윕 (neg: {bneg})", brows, gt_names)

    # ── 게이트 A 판정: 기준 recall 충족 운용점 중 최고 precision(최저 오경보) ──
    if a.base_recall:
        tgt = dict(x.split("=") for x in a.base_recall.split(","))
        print("\n[게이트 A 판정] 기준 recall 충족 & precision 최대(오경보 최소) 운용점:")
        for gn in gt_names:
            if gn not in tgt:
                continue
            thr_t = float(tgt[gn])
            cand = [(r["thr"], r[gn]) for r in rows if r[gn]["R"] is not None and r[gn]["R"] >= thr_t]
            if cand:
                best = max(cand, key=lambda x: x[1]["P"] or 0)
                print(f"  {gn}: 존재 ✅  thr={best[0]}  R={best[1]['R']}  P={best[1]['P']}  FAR={best[1]['FAR']}%  (기준 R≥{thr_t})")
            else:
                print(f"  {gn}: R≥{thr_t} 달성 운용점 없음 ❌")


if __name__ == "__main__":
    main()
