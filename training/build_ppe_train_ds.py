"""ppe RF-DETR 학습용 COCO 데이터셋 빌더 (T10b Phase1).

css_safety(YOLO 포맷, 10클래스) train+valid → COCO(RF-DETR). test 는 게이트 eval 용이라 학습 미포함(격리).
데이터는 ~/Downloads/ppe_rfdetr_ds (리포 밖). T12-B 벤치와 동일 출처·동일 분할 유지.
무결성 검증: 이미지=라벨 수, 클래스 분포, 좌표 범위밖·빈 박스 0건.
"""
import json
import shutil
from collections import Counter
from pathlib import Path

import cv2

_SRC = Path.home() / "Desktop" / "VIGENT" / "data" / "datasets" / "css_safety"
_OUT = Path.home() / "Downloads" / "ppe_rfdetr_ds"
_NAMES = ['Hardhat', 'Mask', 'NO-Hardhat', 'NO-Mask', 'NO-Safety Vest',
          'Person', 'Safety Cone', 'Safety Vest', 'machinery', 'vehicle']   # data.yaml 순서


def build_split(split: str):
    idir_src = _SRC / split / "images"
    ldir_src = _SRC / split / "labels"
    out = _OUT / split
    out.mkdir(parents=True, exist_ok=True)
    images, anns = [], []
    aid = 1
    cls_count = Counter()
    bad_coord = empty_box = 0
    imgs = sorted(list(idir_src.glob("*.jpg")) + list(idir_src.glob("*.png")))
    for iid, ip in enumerate(imgs, 1):
        im = cv2.imread(str(ip))
        if im is None:
            continue
        H, W = im.shape[:2]
        shutil.copy2(ip, out / ip.name)
        images.append({"id": iid, "file_name": ip.name, "width": W, "height": H})
        lp = ldir_src / (ip.stem + ".txt")
        if not lp.exists():
            continue
        for line in lp.read_text().splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            ci = int(float(parts[0]))
            cx, cy, bw, bh = map(float, parts[1:5])
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                bad_coord += 1
                continue
            x, y, w, h = (cx - bw / 2) * W, (cy - bh / 2) * H, bw * W, bh * H
            if w <= 0 or h <= 0:
                empty_box += 1
                continue
            anns.append({"id": aid, "image_id": iid, "category_id": ci + 1,
                         "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
            cls_count[_NAMES[ci] if ci < len(_NAMES) else ci] += 1
            aid += 1
    coco = {"images": images, "annotations": anns,
            "categories": [{"id": i + 1, "name": n, "supercategory": "ppe"} for i, n in enumerate(_NAMES)]}
    (out / "_annotations.coco.json").write_text(json.dumps(coco))
    return len(images), len(anns), cls_count, bad_coord, empty_box


def main():
    if _OUT.exists():
        shutil.rmtree(_OUT)
    total_bad = total_empty = 0
    print("=== ppe COCO 빌드 (css_safety) ===")
    for split in ("train", "valid", "test"):
        ni, na, cc, bad, emp = build_split(split)
        total_bad += bad; total_empty += emp
        print(f"  {split}: {ni}장 / {na} box · 범위밖 {bad} · 빈박스 {emp}")
        if split == "train":
            print("   클래스 분포:", dict(sorted(cc.items(), key=lambda x: -x[1])))
    print(f"  무결성: 범위밖 좌표 {total_bad}건 · 빈 박스 {total_empty}건 (둘 다 0이어야 정상)")
    print(f"  클래스 매핑: YOLO id i → COCO category_id i+1, names={_NAMES}")
    print(f"  → {_OUT}  (test 는 게이트 eval 격리용, 학습은 train+valid)")


if __name__ == "__main__":
    main()
