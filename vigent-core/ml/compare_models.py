"""모델 비교 — 같은 평가셋에 여러 rf-detr 크기를 측정해 표로 정리(어느 모델로 갈지 근거).

사용: python3 vigent-core/ml/compare_models.py data/retrain/office --target person --limit 100 --models nano,small,medium
출력: 콘솔 비교표 + runs/eval/compare_<시각>.json / .md
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_accuracy as ev


def measure(ds: Path, split: str, target: str, conf: float, limit: int, model: str):
    items = ev.load_yolo_gt(ds, split, target.lower())
    if limit:
        items = items[:limit]
    preds, dev, per_img = ev.run_detector(items, target.lower(), conf, model)
    gts = [gt for _p, gt, _wh in items]
    from supervision.metrics import MeanAveragePrecision, Precision, Recall, F1Score
    mAP = MeanAveragePrecision().update(preds, gts).compute()
    prec = Precision().update(preds, gts).compute()
    rec = Recall().update(preds, gts).compute()
    f1 = F1Score().update(preds, gts).compute()
    return {
        "model": f"rf-detr-{model}", "images": len(items),
        "precision": round(float(prec.precision_at_50), 4),
        "recall": round(float(rec.recall_at_50), 4),
        "f1": round(float(f1.f1_50), 4),
        "mAP50": round(float(mAP.map50), 4),
        "ms_per_image": round(per_img * 1000, 1), "device": dev,
        "kisa_pass": bool(prec.precision_at_50 >= 0.9 and rec.recall_at_50 >= 0.9),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--split", default="valid")
    ap.add_argument("--target", default="person")
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--models", default="nano,small,medium")
    args = ap.parse_args()

    ds = Path(args.dataset) if Path(args.dataset).is_absolute() else ROOT / args.dataset
    models = [m.strip() for m in args.models.split(",")]
    print(f"[비교] {ds.name}/{args.split} · 타깃 {args.target} · {args.limit}장 · 모델 {models}\n")

    rows = []
    for m in models:
        print(f"  측정 중: rf-detr-{m} ...")
        t = time.time()
        r = measure(ds, args.split, args.target, args.conf, args.limit, m)
        r["elapsed_s"] = round(time.time() - t, 1)
        rows.append(r)

    # 표 출력
    print("\n──────────────── 모델 비교 (타깃: " + args.target + ") ────────────────")
    print(f"{'모델':<16}{'Precision':>10}{'Recall':>9}{'F1':>8}{'mAP50':>8}{'ms/장':>8}  KISA")
    for r in rows:
        print(f"{r['model']:<16}{r['precision']*100:>9.1f}%{r['recall']*100:>8.1f}%"
              f"{r['f1']*100:>7.1f}%{r['mAP50']*100:>7.1f}%{r['ms_per_image']:>7.0f}  "
              f"{'✅' if r['kisa_pass'] else '❌'}")

    # 추천(F1 최고)
    best = max(rows, key=lambda r: r["f1"])
    print(f"\n  → F1 최고: {best['model']} (F1 {best['f1']*100:.1f}%, {best['ms_per_image']:.0f}ms/장)")

    out_dir = ROOT / "runs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {"dataset": ds.name, "target": args.target, "images": args.limit,
               "measured_at": datetime.now().isoformat(timespec="seconds"), "results": rows,
               "best_f1": best["model"]}
    (out_dir / f"compare_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 마크다운 표
    md = ["# 모델 비교: " + ds.name + " (" + args.target + ")", "",
          "| 모델 | Precision | Recall | F1 | mAP50 | ms/장 | KISA90 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['model']} | {r['precision']*100:.1f}% | {r['recall']*100:.1f}% | "
                  f"{r['f1']*100:.1f}% | {r['mAP50']*100:.1f}% | {r['ms_per_image']:.0f} | "
                  f"{'✅' if r['kisa_pass'] else '❌'} |")
    (out_dir / f"compare_{stamp}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  저장: runs/eval/compare_{stamp}.json / .md")


if __name__ == "__main__":
    main()
