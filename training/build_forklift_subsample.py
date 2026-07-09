"""PoC용 3k 층화 서브샘플 — merged/train 에서 forklift/pallet_truck/네거 비율을 유지해 추출.

test(LOCO 238)·valid 는 건드리지 않고 심링크로 재사용(leakage 유지).
층화 기준: 이미지를 (forklift only / pallet_truck only / both / 네거)로 분류 후 각 그룹 동일 비율 샘플.
결정적(sha256) 샘플링 — 재현 가능.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path("/Users/nohyeonseong/Desktop/VIGENT")
SRC = ROOT / "data/datasets/forklift_merge/merged"
OUT = ROOT / "data/datasets/forklift_merge/subsample3k"
TARGET = 3000
FK, PT = 1, 2

if OUT.exists():
    import shutil
    shutil.rmtree(OUT)

tr = json.loads((SRC / "train/_annotations.coco.json").read_text())
ann_by_img = {}
for a in tr["annotations"]:
    ann_by_img.setdefault(a["image_id"], []).append(a["category_id"])

def group(iid):
    cats = set(ann_by_img.get(iid, []))
    if FK in cats and PT in cats:
        return "both"
    if FK in cats:
        return "fk"
    if PT in cats:
        return "pt"
    return "neg"

groups = {"fk": [], "pt": [], "both": [], "neg": []}
for im in tr["images"]:
    groups[group(im["id"])].append(im)

def score(n):
    return int(hashlib.sha256(("sub_" + n).encode()).hexdigest(), 16) % 100000 / 100000.0

total = len(tr["images"])
frac = TARGET / total
picked = []
for g, ims in groups.items():
    keep = [im for im in ims if score(im["file_name"]) < frac]   # 각 그룹 동일 비율(층화)
    picked.extend(keep)
    print(f"  {g}: {len(ims)} → {len(keep)}")

pick_ids = {im["id"] for im in picked}
anns = [a for a in tr["annotations"] if a["image_id"] in pick_ids]
coco = {"images": picked, "annotations": anns, "categories": tr["categories"]}

# train: 이미지 심링크 + 서브 어노
(OUT / "train").mkdir(parents=True)
(OUT / "train/_annotations.coco.json").write_text(json.dumps(coco))
for im in picked:
    src = SRC / "train" / im["file_name"]
    if src.exists():
        os.symlink(src, OUT / "train" / im["file_name"])

# valid/test 원본 재사용(심링크 전체)
for split in ("valid", "test"):
    (OUT / split).mkdir(parents=True)
    sd = SRC / split
    for f in sd.iterdir():
        os.symlink(f, OUT / split / f.name)

def cnt(c):
    return sum(1 for a in anns if a["category_id"] == c)
print(f"\n서브샘플: train {len(picked)}장 · forklift {cnt(FK)} · pallet_truck {cnt(PT)}")
print(f"  (원본 train 대비 {len(picked)/total*100:.0f}%) · 출력 {OUT}")
