#!/usr/bin/env python3
"""scripts/eval/forklift_fp_dump.py — 지게차 없는 507 음성 2,000장(하네스와 같은 표집)에서 fk 모델이 conf≥0.5 로 낸 오탐을 박스 그려 저장. [2026-09-26 결정 ②(a)]

출력: audit/forklift_fp_507/<번호>_<stem>.jpg + index.json(번호·stem·박스·conf) — 오인 대상(고소작업대/리프트/트럭 등)은 사람이 보고 집계.
사용: python scripts/eval/forklift_fp_dump.py --weights runs/finetune/fk_510_smoke/ckpt/checkpoint_best_total.pth
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from forklift_compare_harness import IMG_EXTS, load_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True); ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--neg-images", default="D:/vigent_private_data/aihub/_inspect/507_src"); ap.add_argument("--neg-limit", type=int, default=2000)
    ap.add_argument("--conf", type=float, default=0.5); ap.add_argument("--out", default=str(_ROOT / "audit" / "forklift_fp_507"))
    a = ap.parse_args()
    import cv2
    import numpy as np
    from PIL import Image
    allimg = sorted(p for p in Path(a.neg_images).rglob("*") if p.suffix.lower() in IMG_EXTS)
    step = max(1, len(allimg) // max(1, a.neg_limit)); negs = allimg[::step][: a.neg_limit]     # 하네스와 동일 표집
    print(f"[fp_dump] 음성 {len(allimg)}장 중 {len(negs)}장 · conf≥{a.conf} · {a.weights}")
    model, ids = load_model(a.weights, a.res)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    index = []; t0 = time.time(); n_fp_img = 0; n_boxes = 0
    for p in negs:
        im = Image.open(p).convert("RGB")
        det = model.predict(im, threshold=a.conf)
        boxes = [([float(v) for v in box], float(c)) for box, cid, c in zip(det.xyxy, det.class_id, det.confidence) if ids is None or int(cid) in ids]
        if not boxes:
            continue
        n_fp_img += 1; n_boxes += len(boxes)
        arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        for (x1, y1, x2, y2), c in boxes:
            cv2.rectangle(arr, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
            cv2.putText(arr, f"forklift? {c:.2f}", (int(x1), max(20, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        dst = out / f"{n_fp_img:03d}_{p.stem}.jpg"
        ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            buf.tofile(str(dst))
        index.append({"no": n_fp_img, "stem": p.stem, "path": str(p), "file": dst.name, "boxes": [{"xyxy": [round(v, 1) for v in b], "conf": round(c, 3)} for b, c in boxes],
                      "folder": p.parent.name})
    (out / "index.json").write_text(json.dumps({"weights": a.weights, "conf": a.conf, "neg_sampled": len(negs), "fp_images": n_fp_img, "fp_boxes": n_boxes, "items": index},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    n_disk = len(list(out.glob("*.jpg")))
    print(f"  오탐 이미지 {n_fp_img}/{len(negs)} ({n_fp_img / len(negs) * 100:.1f}%) · 박스 {n_boxes} · 저장 {n_disk}장 → {out} ({time.time() - t0:.0f}s) ★커밋 금지")
    return 0 if n_disk == n_fp_img else 1


if __name__ == "__main__":
    sys.exit(main())
