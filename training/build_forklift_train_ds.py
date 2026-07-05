"""Phase 0: forklift RF-DETR 학습용 COCO 데이터셋(211 train → train/valid/test).
데이터는 ~/Downloads/loco_forklift_ds (리포 밖). 매니페스트 train 목록만 사용(test/네거 격리 유지)."""
import json, hashlib, shutil
from pathlib import Path

LOCO = Path.home() / "Downloads" / "loco"
DS = Path.home() / "Downloads" / "loco_forklift_ds"
MANI = Path.home() / "Desktop" / "VIGENT" / "benchmarks" / "forklift_eval_manifest.json"
FK_CID = 5

d = json.loads((LOCO / "loco-all-v1.json").read_text())
id2img = {im["id"]: im for im in d["images"]}
name2id = {im["file_name"]: im["id"] for im in d["images"]}
boxes = {}
for a in d["annotations"]:
    if a["category_id"] == FK_CID:
        boxes.setdefault(a["image_id"], []).append(a["bbox"])

train_names = set(json.loads(MANI.read_text())["train_file_names"])   # 211
path_by_name = {p.name: p for p in (LOCO / "dataset").rglob("*.jpg")}

def score(n): return int(hashlib.sha256(n.encode()).hexdigest(), 16) % 10000 / 10000.0
# 결정적 train/valid 분할(211 → valid 10%)
names = sorted(train_names)
valid = [n for n in names if score("v_" + n) < 0.10]
train = [n for n in names if n not in set(valid)]

if DS.exists(): shutil.rmtree(DS)
def emit(split, split_names):
    idir = DS / split; idir.mkdir(parents=True)
    images, anns = [], []
    aid = 1
    for i, name in enumerate(split_names, 1):
        iid = name2id[name]; im = id2img[iid]
        shutil.copy2(path_by_name[name], idir / name)
        images.append({"id": i, "file_name": name, "width": im["width"], "height": im["height"]})
        for (x, y, w, h) in boxes[iid]:
            anns.append({"id": aid, "image_id": i, "category_id": 1,
                         "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
            aid += 1
    coco = {"images": images, "annotations": anns,
            "categories": [{"id": 1, "name": "forklift", "supercategory": "none"}]}
    (idir / "_annotations.coco.json").write_text(json.dumps(coco))
    return len(images), len(anns)

for sp, nm in [("train", train), ("valid", valid), ("test", valid)]:   # test=valid(run_test 대비)
    ni, na = emit(sp, nm)
    print(f"  {sp}: {ni}장 / {na} forklift box")
print("  →", DS)
