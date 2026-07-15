"""forklift 재학습용 병합 COCO 데이터셋 빌더 (Phase 1).

소스: Roboflow 3종(csv2tfrecord·mohamed·robovis, forklift만) + LOCO(forklift + pallet_truck 네거).
클래스 매핑: forklift→1, pallet_truck→2(옵션 B용). person/human/cart→제외. hitsz/vehicle 배제.

출력(2클래스 마스터):
  merged/train|valid|test/  각 _annotations.coco.json + 이미지
  - test = LOCO forklift test 238 고정(baseline 비교 · leakage 방지)
  - valid = 각 Roboflow valid split
  - train = 나머지 전부 + LOCO forklift train 211 + LOCO pallet_truck 네거 1,312

옵션 A(단일 forklift + pallet_truck 네거)는 이 마스터에서 category 2 어노만 제거해 파생(별도 스크립트/플래그).
MPS 미사용(CPU/IO만) — 소크와 병행 가능.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path("/Users/nohyeonseong/Desktop/VIGENT")
SRC = ROOT / "data/datasets/forklift_merge/sources"
LOCO = Path.home() / "Downloads" / "loco"
OUT = ROOT / "data/datasets/forklift_merge/merged"
MANI = json.loads((ROOT / "benchmarks/forklift_eval_manifest.json").read_text())

FK_OUT, PT_OUT = 1, 2   # 통합 category id
CATS = [{"id": FK_OUT, "name": "forklift", "supercategory": "none"},
        {"id": PT_OUT, "name": "pallet_truck", "supercategory": "none"}]

# Roboflow 소스: 폴더명 → (forklift로 매핑할 클래스명 집합). person/human/cart 는 자동 제외.
RF_SOURCES = ["csv2tfrecord_koqxi", "mohamed_dsitv", "robovis_ikbzl"]
FK_NAMES = {"forklift", "forklifts"}   # 대소문자 무시로 매칭

buckets = {"train": {"images": [], "annotations": []},
           "valid": {"images": [], "annotations": []},
           "test": {"images": [], "annotations": []}}
_iid = {"n": 0}
_aid = {"n": 0}
_hashes = set()   # 중복 이미지(내용 해시) 제거
stats = {"dup": 0, "missing": 0, "person_skipped": 0}


def _add(split, src_img: Path, boxes, prefix, w=None, hh=None):
    """이미지+박스 추가. boxes: [(bbox[xywh], out_cat)]. 손상/중복/누락 필터. w/hh=소스 COCO 크기."""
    if not src_img.exists():
        stats["missing"] += 1
        return
    h = hashlib.md5(src_img.read_bytes()).hexdigest()
    if h in _hashes:
        stats["dup"] += 1
        return
    _hashes.add(h)
    if not w or not hh:                     # 소스 메타 없으면 이미지 헤더에서(디코드 없이)
        try:
            from PIL import Image
            with Image.open(src_img) as _im:
                w, hh = _im.size
        except Exception:  # noqa: BLE001
            stats["missing"] += 1
            return
    dst_name = f"{prefix}__{src_img.name}"
    (OUT / split).mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_img, OUT / split / dst_name)
    _iid["n"] += 1
    iid = _iid["n"]
    buckets[split]["images"].append({"id": iid, "file_name": dst_name, "width": w, "height": hh})
    for bbox, cat in boxes:
        _aid["n"] += 1
        x, y, bw, bh = bbox
        buckets[split]["annotations"].append(
            {"id": _aid["n"], "image_id": iid, "category_id": cat,
             "bbox": [x, y, bw, bh], "area": float(bw) * float(bh), "iscrowd": 0})


def ingest_roboflow(name):
    base = SRC / name
    for split_dir in base.iterdir():
        if not split_dir.is_dir():
            continue
        jp = split_dir / "_annotations.coco.json"
        if not jp.exists():
            continue
        d = json.loads(jp.read_text())
        cats = {c["id"]: c["name"].lower() for c in d["categories"]}
        anns_by_img = {}
        for a in d["annotations"]:
            cn = cats.get(a["category_id"], "")
            if cn in FK_NAMES:
                anns_by_img.setdefault(a["image_id"], []).append((a["bbox"], FK_OUT))
            else:
                stats["person_skipped"] += 1
        out_split = "valid" if split_dir.name.lower() in ("valid", "val") else "train"
        for im in d["images"]:
            boxes = anns_by_img.get(im["id"], [])   # forklift 없는 이미지도 배경(네거)로 포함
            _add(out_split, split_dir / im["file_name"], boxes, prefix=name,
                 w=im.get("width"), hh=im.get("height"))


def ingest_loco():
    d = json.loads((LOCO / "loco-all-v1.json").read_text())
    id2img = {im["id"]: im for im in d["images"]}
    name2id = {im["file_name"]: im["id"] for im in d["images"]}
    path_by_name = {p.name: p for p in (LOCO / "dataset").rglob("*.jpg")}
    FK_L, PT_L = 5, 11
    boxes_by_img = {}
    for a in d["annotations"]:
        if a["category_id"] == FK_L:
            boxes_by_img.setdefault(a["image_id"], []).append((a["bbox"], FK_OUT))
        elif a["category_id"] == PT_L:
            boxes_by_img.setdefault(a["image_id"], []).append((a["bbox"], PT_OUT))
    test_names = set(MANI["test_file_names"])
    train_names = set(MANI["train_file_names"])
    # forklift 포함 이미지: test→test, train→train
    fk_imgs = {iid for iid, bs in boxes_by_img.items() if any(c == FK_OUT for _, c in bs)}
    for iid in fk_imgs:
        nm = id2img[iid]["file_name"]
        if nm not in path_by_name:
            stats["missing"] += 1
            continue
        split = "test" if nm in test_names else ("train" if nm in train_names else None)
        if split is None:
            continue   # 매니페스트 밖 forklift 이미지는 격리 원칙상 스킵(재현성)
        _add(split, path_by_name[nm], boxes_by_img[iid], prefix="loco",
             w=id2img[iid].get("width"), hh=id2img[iid].get("height"))
    # pallet_truck-only 이미지 → train 네거(forklift 없음, pallet_truck 박스만). test와 0 겹침(검증됨)
    pt_only = [iid for iid, bs in boxes_by_img.items()
               if all(c == PT_OUT for _, c in bs)]
    for iid in pt_only:
        nm = id2img[iid]["file_name"]
        if nm in test_names or nm not in path_by_name:
            continue
        _add("train", path_by_name[nm], boxes_by_img[iid], prefix="loco_pt",
             w=id2img[iid].get("width"), hh=id2img[iid].get("height"))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for name in RF_SOURCES:
        print(f"[merge] Roboflow {name} ...", flush=True)
        ingest_roboflow(name)
    print("[merge] LOCO forklift + pallet_truck 네거 ...", flush=True)
    ingest_loco()
    for split, b in buckets.items():
        (OUT / split).mkdir(parents=True, exist_ok=True)
        coco = {"images": b["images"], "annotations": b["annotations"], "categories": CATS}
        (OUT / split / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")
    # 요약
    def cnt(split, cat):
        return sum(1 for a in buckets[split]["annotations"] if a["category_id"] == cat)
    print("\n=== 병합 결과 ===", flush=True)
    for split in ("train", "valid", "test"):
        print(f"  {split}: {len(buckets[split]['images'])}장 · "
              f"forklift {cnt(split, FK_OUT)} · pallet_truck {cnt(split, PT_OUT)}", flush=True)
    print(f"  필터: 중복 {stats['dup']} · 누락 {stats['missing']} · person/기타 제외 {stats['person_skipped']}", flush=True)
    print(f"  출력: {OUT}", flush=True)


if __name__ == "__main__":
    main()
