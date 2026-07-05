"""ppe NaN 진단용 소형 서브셋 빌더 (T10b). ppe_rfdetr_ds(전체) → ppe_subset(~200 train/40 valid).
1-epoch 스모크런 빠른 반복용(발산 원인 규명). 클래스·포맷 동일, 결정적(SHA256) 표본.
"""
import hashlib
import json
import shutil
from pathlib import Path

_SRC = Path.home() / "Downloads" / "ppe_rfdetr_ds"
_OUT = Path.home() / "Downloads" / "ppe_subset"
_N = {"train": 200, "valid": 40}


def _score(name: str) -> float:
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % 10000 / 10000


def build_split(split: str, n: int):
    src = _SRC / split
    coco = json.loads((src / "_annotations.coco.json").read_text())
    imgs = coco["images"]
    # 결정적 표본: SHA 점수 하위 n장
    imgs_sorted = sorted(imgs, key=lambda im: _score(im["file_name"]))[:n]
    keep_ids = {im["id"] for im in imgs_sorted}
    anns = [a for a in coco["annotations"] if a["image_id"] in keep_ids]
    out = _OUT / split
    out.mkdir(parents=True, exist_ok=True)
    for im in imgs_sorted:
        shutil.copy2(src / im["file_name"], out / im["file_name"])
    (out / "_annotations.coco.json").write_text(json.dumps(
        {"images": imgs_sorted, "annotations": anns, "categories": coco["categories"]}))
    return len(imgs_sorted), len(anns)


def main():
    if _OUT.exists():
        shutil.rmtree(_OUT)
    print("=== ppe 진단 서브셋 빌드 ===")
    for split, n in _N.items():
        ni, na = build_split(split, n)
        print(f"  {split}: {ni}장 / {na} box")
    print(f"  → {_OUT} (1-epoch 스모크 전용)")


if __name__ == "__main__":
    main()
