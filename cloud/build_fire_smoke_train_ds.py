"""fire_smoke RF-DETR 학습셋 빌더 (T10b 대안D). D-Fire(YOLO) → COCO.
정책(대안D): 모든 positive 이미지 + 네거티브 2000장(빈 라벨)만 포함(연무·구름 등 hard negative 우선은
  자동판별 불가 → 결정적 SHA 표본, hard-neg 큐레이션은 수동 정제 대상으로 명시).
클래스: D-Fire 0=smoke, 1=fire → COCO category 1=smoke, 2=fire.
무결성 검사(ppe 빌더와 동일): 좌표 범위·wh>0·class id 0/1·이미지 RGB.
사용: python build_fire_smoke_train_ds.py --dfire /workspace/data/dfire --out /workspace/data/fire_rfdetr_ds --neg 2000
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import cv2

_NAMES = ["smoke", "fire"]   # D-Fire 0=smoke, 1=fire


def _score(name: str) -> float:
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % 100000 / 100000


def _load(split_dir: Path):
    idir, ldir = split_dir / "images", split_dir / "labels"
    imgs = sorted(list(idir.glob("*.jpg")) + list(idir.glob("*.png")))
    pos, neg = [], []
    for ip in imgs:
        lp = ldir / (ip.stem + ".txt")
        has = lp.exists() and lp.stat().st_size > 0
        (pos if has else neg).append((ip, lp if has else None))
    return pos, neg


def _write_coco(items, out: Path, ldir_lookup, stats):
    out.mkdir(parents=True, exist_ok=True)
    images, anns = [], []
    aid = 1
    for iid, (ip, lp) in enumerate(items, 1):
        im = cv2.imread(str(ip))
        if im is None:
            stats["unreadable"] += 1
            continue
        H, W = im.shape[:2]
        shutil.copy2(ip, out / ip.name)
        images.append({"id": iid, "file_name": ip.name, "width": W, "height": H})
        if lp is None:
            continue
        for line in lp.read_text().splitlines():
            p = line.split()
            if len(p) < 5:
                continue
            ci = int(float(p[0]))
            cx, cy, bw, bh = map(float, p[1:5])
            if ci not in (0, 1):
                stats["bad_cls"] += 1
                continue
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                stats["bad_coord"] += 1
                continue
            x, y, w, h = (cx - bw / 2) * W, (cy - bh / 2) * H, bw * W, bh * H
            if w <= 0 or h <= 0:
                stats["degen"] += 1
                continue
            anns.append({"id": aid, "image_id": iid, "category_id": ci + 1,
                         "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0})
            aid += 1
    coco = {"images": images, "annotations": anns,
            "categories": [{"id": i + 1, "name": n, "supercategory": "fire_smoke"} for i, n in enumerate(_NAMES)]}
    (out / "_annotations.coco.json").write_text(json.dumps(coco))
    return len(images), len(anns)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dfire", required=True, help="D-Fire 루트(train/ test/ 포함)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--neg", type=int, default=2000)
    ap.add_argument("--valid", type=int, default=200)
    a = ap.parse_args()

    dfire, out = Path(a.dfire), Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    stats = {"unreadable": 0, "bad_cls": 0, "bad_coord": 0, "degen": 0}

    pos, neg = _load(dfire / "train")
    neg_sorted = sorted(neg, key=lambda t: _score(t[0].name))[:a.neg]   # 결정적 2000 네거
    print(f"=== fire_smoke 대안D 빌드 ===")
    print(f"  D-Fire train: positive {len(pos)} · negative {len(neg)}(→ {len(neg_sorted)} 채택)")

    # valid: positive 에서 결정적 슬라이스
    pos_sorted = sorted(pos, key=lambda t: _score("v" + t[0].name))
    valid_items = pos_sorted[:a.valid]
    train_items = pos_sorted[a.valid:] + neg_sorted

    nv_i, nv_a = _write_coco(valid_items, out / "valid", None, stats)
    nt_i, nt_a = _write_coco(train_items, out / "train", None, stats)
    print(f"  train: {nt_i}장 / {nt_a} box (positive {len(pos)-a.valid} + neg {len(neg_sorted)})")
    print(f"  valid: {nv_i}장 / {nv_a} box")
    print(f"  무결성: unreadable {stats['unreadable']} · bad_cls {stats['bad_cls']} · "
          f"bad_coord {stats['bad_coord']} · degenerate {stats['degen']} (모두 0이어야 정상)")
    print(f"  클래스: 0=smoke→cat1, 1=fire→cat2. hard-neg 큐레이션은 수동 정제 대상(현재 결정적 표본).")
    print(f"  → {out}")


if __name__ == "__main__":
    main()
