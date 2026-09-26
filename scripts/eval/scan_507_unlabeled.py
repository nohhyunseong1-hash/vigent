#!/usr/bin/env python3
"""scripts/eval/scan_507_unlabeled.py — 507 train 프레임에 v1(ppe_rfdetr_v1)을 돌려 **라벨에 없는 클래스**(조끼 착용/미착용, 안전모 착용)의 박스가 얼마나 있는지 센다. [2026-09-27 결정 ③ 전 측정]

가설: 507 라벨은 NO-Hardhat(WO-04)·person 뿐이라, 조끼·착용 안전모가 화면에 있어도 "배경"으로 학습된다(라벨 누락 음성). 이 스크립트는 그 규모를 잰다.
출력: audit/scan_507_unlabeled.json + 미리보기 30장(조끼 박스 빨강·NO-조끼 자주·Hardhat 초록, conf≥0.6) → audit/507_vest_unlabeled/ (커밋 금지)
사용: python scripts/eval/scan_507_unlabeled.py [--conf 0.6] [--limit 0] [--preview-n 30]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VEST = {"Safety Vest": "Safety-Vest", "NO-Safety Vest": "NO-Safety-Vest"}
HAT = {"Hardhat": "Hardhat"}
COLORS = {"Safety-Vest": (0, 0, 255), "NO-Safety-Vest": (200, 0, 200), "Hardhat": (0, 200, 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vigent507", default="D:/vigent_private_data/aihub/vigent_507"); ap.add_argument("--images", default="D:/vigent_private_data/aihub/_inspect/507_src")
    ap.add_argument("--conf", type=float, default=0.6); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--preview-n", type=int, default=30)
    ap.add_argument("--preview-dir", default=str(_ROOT / "audit" / "507_vest_unlabeled")); ap.add_argument("--out", default=str(_ROOT / "audit" / "scan_507_unlabeled.json"))
    ap.add_argument("--seed", type=int, default=20260927)
    a = ap.parse_args()
    import cv2
    import numpy as np
    from aihub_smoke_eval import class_names_of, load_model
    from PIL import Image
    v = Path(a.vigent507); sp = json.loads((v / "split.json").read_text(encoding="utf-8"))
    idx = {p.stem: p for p in Path(a.images).rglob("*.jpg")}
    stems = [s for s in sp["train"] if s in idx]
    if a.limit:
        stems = stems[: a.limit]
    # 507 라벨의 클래스 분포(train)
    names = (v / "classes.txt").read_text(encoding="utf-8").split(); lab = Counter()
    for s in stems:
        for ln in (v / "labels" / f"{s}.txt").read_text(encoding="utf-8").splitlines():
            t = ln.split()
            if t:
                lab[names[int(t[0])]] += 1
    print(f"[scan_507] train 프레임 {len(stems)}장 · 라벨 분포 {dict(lab)} · v1 conf≥{a.conf}")
    model, dev = load_model("ppe", 384); cn = class_names_of(model)
    box_cnt = Counter(); img_with = Counter(); per_img = []
    t0 = time.time()
    for i, s in enumerate(stems, 1):
        im = Image.open(idx[s]).convert("RGB")
        det = model.predict(im, threshold=a.conf)
        found = []
        for box, cid, c in zip(det.xyxy, det.class_id, det.confidence):
            raw = cn.get(int(cid), ""); std = VEST.get(raw) or HAT.get(raw)
            if std:
                found.append((std, [float(x) for x in box], float(c))); box_cnt[std] += 1
        kinds = {k for k, _, _ in found}
        for k in kinds:
            img_with[k] += 1
        if "Safety-Vest" in kinds or "NO-Safety-Vest" in kinds:
            img_with["any_vest"] += 1
        per_img.append({"stem": s, "path": str(idx[s]), "boxes": found})
        if i % 500 == 0:
            print(f"  {i}/{len(stems)} ({time.time() - t0:.0f}s)")
    n = len(stems)
    res = {"date": time.strftime("%Y-%m-%d %H:%M"), "model": "ppe_rfdetr_v1 @>=%.2f" % a.conf, "frames": n, "label_counts_507_train": dict(lab),
           "boxes": dict(box_cnt), "images_with": dict(img_with),
           "ratio_pct": {k: round(img_with[k] / n * 100, 1) for k in ("any_vest", "Safety-Vest", "NO-Safety-Vest", "Hardhat")},
           "per_image_stats": {"vest_boxes_per_image_with_vest": round(sum(1 for p in per_img for b in p["boxes"] if b[0].endswith("Vest")) / max(1, img_with["any_vest"]), 2)}}
    # 미리보기: 조끼 박스가 있는 이미지 중 무작위 30
    pv = Path(a.preview_dir); pv.mkdir(parents=True, exist_ok=True)
    cand = [p for p in per_img if any(b[0].endswith("Vest") for b in p["boxes"])]
    rnd = random.Random(a.seed); pick = rnd.sample(cand, min(a.preview_n, len(cand))); ok = 0; index = []
    for k, p in enumerate(pick, 1):
        arr = cv2.imdecode(np.fromfile(p["path"], np.uint8), cv2.IMREAD_COLOR)
        for std, (x1, y1, x2, y2), c in p["boxes"]:
            cv2.rectangle(arr, (int(x1), int(y1)), (int(x2), int(y2)), COLORS[std], 3)
            cv2.putText(arr, f"{std} {c:.2f}", (int(x1), max(20, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, COLORS[std], 2)
        dst = pv / f"{k:02d}_{p['stem']}.jpg"; okw, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if okw:
            buf.tofile(str(dst)); ok += 1
        index.append({"no": k, "stem": p["stem"], "boxes": [(s_, round(c, 2)) for s_, _, c in p["boxes"]]})
    (pv / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    res["preview"] = {"saved": ok, "dir": str(pv)}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("| 항목 | 507 라벨(train) | v1 conf≥%.1f 박스 | 박스 있는 이미지 | 비율 |" % a.conf); print("|---|---|---|---|---|")
    for std, key in (("Safety-Vest", "Safety-Vest"), ("NO-Safety-Vest", "NO-Safety-Vest"), ("Hardhat", "Hardhat")):
        print(f"| {std} | {lab.get(std, 0)} | {box_cnt[std]} | {img_with[key]} | {res['ratio_pct'][key]} % |")
    print(f"| 조끼(둘 중 하나) | 0 | {box_cnt['Safety-Vest'] + box_cnt['NO-Safety-Vest']} | {img_with['any_vest']} | **{res['ratio_pct']['any_vest']} %** |")
    print(f"미리보기 {ok}/{len(pick)}장 → {pv} · 원자료 {a.out} · {time.time() - t0:.0f}s")
    return 0 if ok == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main())
