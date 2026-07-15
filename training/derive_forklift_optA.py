"""옵션 A 파생 — 2클래스 마스터(merged)에서 단일 forklift + pallet_truck 하드네거 데이터셋 생성.

pallet_truck(cat 2) 어노테이션을 제거하되 **이미지는 유지**(forklift 없는 배경 = hard negative).
→ 모델이 pallet_truck 을 'forklift 아님(배경)'으로 학습 → pallet_truck 오탐(FAR 바닥) 억제.
이미지는 심링크(공간 절약). category = [forklift] 단일.

MPS NaN 버그가 2클래스 학습을 막을 때의 폴백 경로(단일클래스는 MPS 학습 성공 이력).
"""
import json
import os
from pathlib import Path

ROOT = Path("/Users/nohyeonseong/Desktop/VIGENT")
SRC = ROOT / "data/datasets/forklift_merge/merged"
OUT = ROOT / "data/datasets/forklift_merge/merged_optA"
FK = 1

if OUT.exists():
    import shutil
    shutil.rmtree(OUT)

for split in ("train", "valid", "test"):
    sdir = SRC / split
    if not (sdir / "_annotations.coco.json").exists():
        continue
    d = json.loads((sdir / "_annotations.coco.json").read_text())
    # forklift 어노만 유지(pallet_truck 제거). 이미지는 전부 유지(네거 포함)
    anns = [a for a in d["annotations"] if a["category_id"] == FK]
    coco = {"images": d["images"], "annotations": anns,
            "categories": [{"id": FK, "name": "forklift", "supercategory": "none"}]}
    odir = OUT / split
    odir.mkdir(parents=True, exist_ok=True)
    (odir / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")
    # 이미지 심링크(원본 재사용)
    for im in d["images"]:
        src = sdir / im["file_name"]
        dst = odir / im["file_name"]
        if src.exists() and not dst.exists():
            os.symlink(src, dst)
    fk = len(anns)
    neg = sum(1 for im in d["images"] if im["id"] not in {a["image_id"] for a in anns})
    print(f"  {split}: {len(d['images'])}장 · forklift {fk} · 네거(배경) {neg}")
print(f"옵션 A 출력: {OUT}")
