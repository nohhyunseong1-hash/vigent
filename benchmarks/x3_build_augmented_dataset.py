#!/usr/bin/env python3
"""[X-3] 재학습 1라운드 — 증강 학습셋 생성(css v27 train, COCO 포맷).

[V-1/W-1]에서 승인된 3종 증강만 적용한다(블러 계열 없음):
  - person random erasing(가림, 차폐비율 20~55%)
  - person copy-paste 가림(css v27 machinery/vehicle/Safety Cone 오브젝트)
  - Hardhat/NO-Hardhat 축소(구분 가능한 소수를 위해 유지, 목표 폭 14~52px)

원본 이미지는 손상 없이 보존(하드링크로 새 디렉터리에 배치, 디스크 복제 없음)하고, 증강본은
새 파일로 추가한다 — 즉 학습셋은 "원본 + 증강 사본"이지 원본을 대체하지 않는다.
data/field_eval/(dev/test) 프레임은 이 데이터셋에 전혀 관여하지 않는다(별개 데이터 소스,
css v27 자체가 field_eval 9종 영상과 무관 — [U-1]의 "field_eval 원본 프레임 학습 금지" 규칙과
별개 축이지만 동일하게 준수됨: css v27은애초에 field_eval 소스가 아니다).
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from v1_augmentation_preview import TARGET_HEAD_W_PX, random_erase  # noqa: E402
from v1b_copypaste_occlusion import build_crop_bank, copy_paste_occlude  # noqa: E402

SRC_ROOT = _ROOT / "data" / "datasets" / "css_safety_coco"
OUT_ROOT = _ROOT / "data" / "datasets" / "css_safety_aug"

CATS = {"Hardhat": 1, "Mask": 2, "NO-Hardhat": 3, "NO-Mask": 4, "NO-Safety Vest": 5,
        "Person": 6, "Safety Cone": 7, "Safety Vest": 8, "machinery": 9, "vehicle": 10}
PERSON_ID = CATS["Person"]
HARDHAT_IDS = {CATS["Hardhat"], CATS["NO-Hardhat"]}

P_PERSON_AUG = 0.5      # person 있는 이미지 중 가림 증강 사본을 만들 비율
P_SCALE_AUG = 0.3        # Hardhat/NO-Hardhat 있는 이미지 중 축소 증강 사본을 만들 비율
ERASE_AREA_FRAC = (0.20, 0.55)
BANK_SIZE = 200
RNG = random.Random(42)


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)   # 같은 볼륨(D:)이면 즉시·무복제
    except OSError:
        import shutil
        shutil.copy2(src, dst)


def _to_norm_boxes(anns: list[dict], w: int, h: int) -> list[list[float]]:
    out = []
    for a in anns:
        x, y, bw, bh = a["bbox"]
        out.append([x / w, y / h, (x + bw) / w, (y + bh) / h])
    return out


def _scale_reduce_all(img: np.ndarray, boxes: list[list[float]], anchor_idx: int,
                       target_w_px: int) -> tuple[np.ndarray, list[list[float]]]:
    h, w = img.shape[:2]
    ref = boxes[anchor_idx]
    cur_w_px = (ref[2] - ref[0]) * w
    if cur_w_px <= 0:
        return img, boxes
    scale = max(0.05, min(1.0, target_w_px / cur_w_px))
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    small = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    ox, oy = (w - new_w) // 2, (h - new_h) // 2
    canvas[oy:oy + new_h, ox:ox + new_w] = small
    new_boxes = []
    for bx in boxes:
        x1, y1, x2, y2 = bx
        nx1 = (ox + x1 * new_w) / w
        ny1 = (oy + y1 * new_h) / h
        nx2 = (ox + x2 * new_w) / w
        ny2 = (oy + y2 * new_h) / h
        new_boxes.append([nx1, ny1, nx2, ny2])
    return canvas, new_boxes


def _copy_split_unchanged(split: str) -> None:
    src_dir = SRC_ROOT / split
    dst_dir = OUT_ROOT / split
    dst_dir.mkdir(parents=True, exist_ok=True)
    coco = json.loads((src_dir / "_annotations.coco.json").read_text(encoding="utf-8"))
    for img in coco["images"]:
        _link_or_copy(src_dir / img["file_name"], dst_dir / img["file_name"])
    (dst_dir / "_annotations.coco.json").write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
    print(f"{split}: {len(coco['images'])}장(원본 그대로, 하드링크)")


def build_train() -> None:
    src_dir = SRC_ROOT / "train"
    dst_dir = OUT_ROOT / "train"
    dst_dir.mkdir(parents=True, exist_ok=True)
    coco = json.loads((src_dir / "_annotations.coco.json").read_text(encoding="utf-8"))

    print("copy-paste 은행 구축 중(machinery/vehicle/Safety Cone, css v27 train)...")
    bank = build_crop_bank(RNG, BANK_SIZE)
    print(f"은행 크기: {len(bank)}")

    anns_by_img: dict[int, list[dict]] = {}
    for a in coco["annotations"]:
        anns_by_img.setdefault(a["image_id"], []).append(a)

    next_img_id = max(im["id"] for im in coco["images"]) + 1
    next_ann_id = max(a["id"] for a in coco["annotations"]) + 1
    new_images: list[dict] = []
    new_anns: list[dict] = []
    n_person_aug = 0
    n_scale_aug = 0

    for img_meta in coco["images"]:
        img_id = img_meta["id"]
        fname = img_meta["file_name"]
        _link_or_copy(src_dir / fname, dst_dir / fname)
        anns = anns_by_img.get(img_id, [])
        if not anns:
            continue
        w, h = img_meta["width"], img_meta["height"]

        person_idxs = [i for i, a in enumerate(anns) if a["category_id"] == PERSON_ID
                       and a["bbox"][2] / w >= 0.05 and a["bbox"][3] / h >= 0.08]
        hardhat_idxs = [i for i, a in enumerate(anns) if a["category_id"] in HARDHAT_IDS]

        img = None  # lazy load

        if person_idxs and RNG.random() < P_PERSON_AUG:
            if img is None:
                img = cv2.imread(str(src_dir / fname))
            if img is not None:
                boxes = _to_norm_boxes(anns, w, h)
                pidx = RNG.choice(person_idxs)
                pbox = boxes[pidx]
                if RNG.random() < 0.5:
                    aug_img = random_erase(img, pbox, ERASE_AREA_FRAC, RNG)
                else:
                    aug_img = copy_paste_occlude(img, pbox, bank, ERASE_AREA_FRAC, RNG)
                new_fname = f"aug_erase_{img_id}_{fname}"
                cv2.imwrite(str(dst_dir / new_fname), aug_img)
                new_images.append({"id": next_img_id, "file_name": new_fname, "width": w, "height": h})
                for a in anns:
                    new_a = dict(a)
                    new_a["id"] = next_ann_id
                    new_a["image_id"] = next_img_id
                    new_anns.append(new_a)
                    next_ann_id += 1
                next_img_id += 1
                n_person_aug += 1

        if hardhat_idxs and RNG.random() < P_SCALE_AUG:
            if img is None:
                img = cv2.imread(str(src_dir / fname))
            if img is not None:
                boxes = _to_norm_boxes(anns, w, h)
                anchor = max(hardhat_idxs, key=lambda i: (boxes[i][2] - boxes[i][0]))
                target_w = RNG.randint(*TARGET_HEAD_W_PX)
                aug_img, new_boxes = _scale_reduce_all(img, boxes, anchor, target_w)
                new_fname = f"aug_scale_{img_id}_{fname}"
                cv2.imwrite(str(dst_dir / new_fname), aug_img)
                new_images.append({"id": next_img_id, "file_name": new_fname, "width": w, "height": h})
                for a, nb in zip(anns, new_boxes):
                    new_a = dict(a)
                    new_a["id"] = next_ann_id
                    new_a["image_id"] = next_img_id
                    nx1, ny1, nx2, ny2 = nb
                    new_a["bbox"] = [nx1 * w, ny1 * h, max(1.0, (nx2 - nx1) * w), max(1.0, (ny2 - ny1) * h)]
                    new_anns.append(new_a)
                    next_ann_id += 1
                next_img_id += 1
                n_scale_aug += 1

    coco["images"].extend(new_images)
    coco["annotations"].extend(new_anns)
    (dst_dir / "_annotations.coco.json").write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")

    print(f"\ntrain 원본: {len(coco['images']) - len(new_images)}장")
    print(f"person 가림 증강 사본: {n_person_aug}장")
    print(f"NO-Hardhat/Hardhat 축소 증강 사본: {n_scale_aug}장")
    print(f"train 최종: {len(coco['images'])}장, annotations: {len(coco['annotations'])}건")


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    build_train()
    _copy_split_unchanged("valid")
    _copy_split_unchanged("test")
    print(f"\n증강 학습셋: {OUT_ROOT}")


if __name__ == "__main__":
    main()
