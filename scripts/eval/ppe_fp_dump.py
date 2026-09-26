#!/usr/bin/env python3
"""scripts/eval/ppe_fp_dump.py — held-out 91장에서 지정 클래스(기본 Safety Vest)의 오탐(GT 와 IoU<0.5)을 박스 그려 저장. [2026-09-27 결정 ①]

사용: python scripts/eval/ppe_fp_dump.py --weights runs/finetune/ppe_507_v2/ckpt/checkpoint_best_total.pth --cls "Safety Vest" --n 10 --out audit/ppe_A_fp
그림: 빨강 = 오탐 예측(conf), 초록 = 같은 클래스 GT, 파랑 = 다른 클래스 GT(라벨 표기) — 무엇을 조끼로 오인했는지 보기 위함.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import eval_v1_heldout as H  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True); ap.add_argument("--cls", default="Safety Vest"); ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--n", type=int, default=10); ap.add_argument("--out", default=str(_ROOT / "audit" / "ppe_A_fp")); ap.add_argument("--res", type=int, default=384)
    a = ap.parse_args()
    import cv2
    import numpy as np
    import torch
    import yaml
    from PIL import Image
    from rfdetr import RFDETRNano
    names = yaml.safe_load((H.DS / "data.yaml").read_text(encoding="utf-8"))["names"]
    imgs, _ = H.build_heldout("video")
    m = RFDETRNano(pretrain_weights=a.weights, device="cuda" if torch.cuda.is_available() else "cpu", resolution=a.res)
    cls_names = [H.to_css_name(c) for c in (getattr(m, "class_names", None) or names)]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); items = []; n_fp = 0; n_pred = 0
    for p in imgs:
        gts = H.load_gt(p, names)
        det = m.predict(Image.open(p).convert("RGB"), threshold=a.conf)
        preds = [(cls_names[int(c)], [float(x) for x in b], float(cf)) for b, c, cf in zip(det.xyxy, det.class_id, det.confidence) if 0 <= int(c) < len(cls_names)]
        mine = [pr for pr in preds if pr[0] == a.cls]; n_pred += len(mine)
        fps = [(name, conf, box) for (name, conf, tp), (_n, box, _c) in zip(H.match(mine, [g for g in gts if g[0] == a.cls], 0.5), sorted(mine, key=lambda x: -x[2])) if not tp]
        if not fps:
            continue
        n_fp += len(fps)
        if len(items) >= a.n:
            continue
        arr = cv2.cvtColor(np.array(Image.open(p).convert("RGB")), cv2.COLOR_RGB2BGR)
        for gname, gbox in gts:
            col = (0, 200, 0) if gname == a.cls else (255, 120, 0)
            cv2.rectangle(arr, (int(gbox[0]), int(gbox[1])), (int(gbox[2]), int(gbox[3])), col, 1)
            cv2.putText(arr, gname, (int(gbox[0]), max(10, int(gbox[1]) - 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1)
        for name, conf, box in fps:
            cv2.rectangle(arr, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 0, 255), 2)
            cv2.putText(arr, f"FP {name} {conf:.2f}", (int(box[0]), max(12, int(box[1]) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        dst = out / f"{len(items) + 1:02d}_{p.stem}.jpg"; cv2.imwrite(str(dst), arr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        items.append({"no": len(items) + 1, "file": p.name, "fps": [{"conf": round(c, 3), "box": [round(v) for v in b]} for _, c, b in fps],
                      "gt_classes": sorted({g for g, _ in gts})})
    (out / "index.json").write_text(json.dumps({"weights": a.weights, "cls": a.cls, "conf": a.conf, "pred_total": n_pred, "fp_total": n_fp, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_disk = len(list(out.glob("*.jpg")))
    print(f"[ppe_fp_dump] {a.cls}: 예측 {n_pred} · 오탐 {n_fp} · 저장 {n_disk}/{len(items)} → {out} ★커밋 금지")
    return 0 if n_disk == len(items) else 1


if __name__ == "__main__":
    sys.exit(main())
