#!/usr/bin/env python3
"""scripts/eval/forklift_neg_eval.py — 510 원천 폴더(예: VS_02 보관)에서 **라벨상 지게차가 없는 프레임만** 골라 음성 전용 오탐률을 잰다. [2026-09-26 결정 ②(b)]

라벨(510_all)로 GT 를 읽으므로 "지게차 없음" 은 추정이 아니라 라벨 근거다(WO-04 박스 0개). 지게차가 있는 프레임은 따로 세어 재현율도 같이 낸다.
오탐 이미지는 박스를 그려 --dump 폴더에 저장(시저리프트 등 오인 대상 육안 확인용, 커밋 금지).

사용:
    python scripts/eval/forklift_neg_eval.py --weights vigent-core/weights/forklift_rfdetr_fk510_smoke.pth \
        --images D:/vigent_private_data/aihub/_inspect/510_src/VS_02 --labels D:/vigent_private_data/aihub/_inspect/510_all --tag VS02
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(_ROOT / "vigent-core"))
import defaults as _defaults  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aihub_smoke_eval import gt_from_aihub  # noqa: E402
from eval_v1_heldout import wilson  # noqa: E402
from forklift_compare_harness import eval_510, load_model  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True); ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--images", required=True); ap.add_argument("--labels", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--conf", type=float, default=_defaults.FORKLIFT_OP_CONF); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dump", default="", help="오탐 이미지 저장 폴더(기본 audit/forklift_fp_<tag>)")
    a = ap.parse_args()
    import cv2
    import numpy as np
    from PIL import Image
    items_all = gt_from_aihub("510", Path(a.labels), Path(a.images))
    items = [(img, [b for c, b, _ in boxes if c == "forklift"]) for img, boxes in items_all]
    if a.limit:
        items = items[: a.limit]
    neg = [(i, g) for i, g in items if not g]; pos = [(i, g) for i, g in items if g]
    print(f"[neg_eval {a.tag}] 라벨 매칭 이미지 {len(items)} · 지게차 없음(음성) {len(neg)} · 있음 {len(pos)} · conf {a.conf}")
    model, ids = load_model(a.weights, a.res)

    def predict_pil(im):
        det = model.predict(im, threshold=0.001)
        return [([float(v) for v in box], float(c)) for box, cid, c in zip(det.xyxy, det.class_id, det.confidence) if ids is None or int(cid) in ids]

    t0 = time.time()
    r = eval_510(items, lambda p: predict_pil(Image.open(p).convert("RGB")), a.conf)
    r["elapsed_s"] = round(time.time() - t0, 1)
    print(json.dumps({k: r[k] for k in ("images", "gt", "pos_images", "neg_images", "neg_fp_rate", "neg_fp_rate_ci95", "neg_fp_rate_03", "recall", "recall_ci95", "precision", "ap50")}, ensure_ascii=False))
    # 오탐 이미지 저장(음성 중 conf≥0.5 박스가 있는 것)
    dump = Path(a.dump) if a.dump else _ROOT / "audit" / f"forklift_fp_{a.tag}"
    dump.mkdir(parents=True, exist_ok=True); fp_items = []
    for img, _g in neg:
        im = Image.open(img).convert("RGB")
        boxes = [(b, c) for b, c in predict_pil(im) if c >= a.conf]
        if not boxes:
            continue
        arr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        for (x1, y1, x2, y2), c in boxes:
            cv2.rectangle(arr, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
            cv2.putText(arr, f"forklift? {c:.2f}", (int(x1), max(20, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        dst = dump / f"{len(fp_items) + 1:03d}_{img.stem}.jpg"
        ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            buf.tofile(str(dst))
        fp_items.append({"no": len(fp_items) + 1, "stem": img.stem, "file": dst.name, "folder": img.parent.name, "conf": [round(c, 3) for _, c in boxes]})
    n_disk = len(list(dump.glob("*.jpg")))
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "tag": a.tag, "weights": a.weights, "images_root": a.images, "labels_root": a.labels, "conf": a.conf,
           "result": r, "neg_fp_images": len(fp_items), "wilson_neg_fp": wilson(len(fp_items), len(neg)) if neg else None, "fp_items": fp_items,
           "note": "음성 = 510 라벨(WO-04) 상 지게차 박스 0개인 프레임. 오탐 = conf≥0.5 forklift 박스 1개 이상"}
    p = _ROOT / "audit" / f"forklift_neg_eval_{a.tag}_{time.strftime('%Y%m%d_%H%M')}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  오탐 {len(fp_items)}/{len(neg)} = {r['neg_fp_rate']}% {r['neg_fp_rate_ci95']} · 저장 {n_disk}장 → {dump} · 원자료 {p.name} ★커밋 금지")
    return 0 if n_disk == len(fp_items) else 1


if __name__ == "__main__":
    sys.exit(main())
