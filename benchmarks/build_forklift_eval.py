"""build_forklift_eval.py — LOCO forklift 평가셋 결정적 구축 (T13b).

배경: LOCO 는 파렛트 중심 → forklift 가 가장 희소(598 inst / 449 img). 80/20 분할 시 test 가 ~89장으로
기준(150img/300inst) 미달. 결정(사용자): **SHA256 결정적 분할 유지 + 희소 class 라 test 비율 상향** —
50%부터 시작해 test 가 ≥150img AND ≥300inst 될 때까지 비율을 올려(최대 60%) 최소 충족 비율 채택.
baseline(YOLO)·T10b(RF-DETR) 모두 이 test 분할로만 측정(같은 시험지), RF-DETR 학습은 train 분할만.

결정성: score(img) = int(sha256(file_name),16) % 10000 / 10000 ∈ [0,1). test if score < ratio.
  비율을 올리면 test 는 단조 증가(중첩) → 재현 가능·안정.

출력: benchmarks/data/forklift/{images,labels(YOLO)}/ + data.yaml + instances.json + 매니페스트(train/test 목록).
실행: /opt/anaconda3/bin/python3 benchmarks/build_forklift_eval.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOCO = Path.home() / "Downloads" / "loco"
_JSON = _LOCO / "loco-all-v1.json"
_SRC_IMG_ROOT = _LOCO / "dataset"
_OUT = _ROOT / "benchmarks" / "data" / "forklift"
_MANIFEST = _ROOT / "benchmarks" / "forklift_eval_manifest.json"
_FORKLIFT_CID = 5           # LOCO category id (forklift)
_PALLET_TRUCK_CID = 11      # LOCO category id (pallet_truck) — hard negative(동력 지게차와 최혼동)
_MIN_IMG, _MIN_INST = 150, 300
_RATIOS = [0.50, 0.55, 0.60]
_NEG_TOTAL = 80             # test 전용 네거티브 수(FAR 측정용)
_NEG_HARD_FRAC = 0.5        # hard(pallet_truck 등장) 비율 — 나머지는 일반 창고 장면
#  네거티브 조건(사용자): forklift 0개 이미지만(라벨 오염 방지), hard 30~50%=pallet_truck,
#  test 전용(T10b 학습 no-inject 목록으로 커밋).


def _score(name: str) -> float:
    return int(hashlib.sha256(name.encode()).hexdigest(), 16) % 10000 / 10000.0


def main():
    d = json.loads(_JSON.read_text())
    id2img = {im["id"]: im for im in d["images"]}
    # forklift 어노테이션만 → 이미지별 박스 목록
    boxes_by_img: dict[int, list] = defaultdict(list)
    for a in d["annotations"]:
        if a["category_id"] == _FORKLIFT_CID:
            boxes_by_img[a["image_id"]].append(a["bbox"])   # COCO [x,y,w,h] px
    fk_imgs = sorted(boxes_by_img)                            # forklift 등장 이미지 id
    print(f"forklift 이미지 {len(fk_imgs)} / 인스턴스 {sum(len(v) for v in boxes_by_img.values())}")

    # basename → 실제 경로 매핑(subset-N 하위). 충돌 검사.
    path_by_name: dict[str, Path] = {}
    for p in _SRC_IMG_ROOT.rglob("*.jpg"):
        assert p.name not in path_by_name, f"basename 충돌: {p.name}"
        path_by_name[p.name] = p

    # 비율 탐색: test 가 기준 충족하는 최소 비율
    chosen = None
    print(f"\n비율 탐색(test ≥{_MIN_IMG}img AND ≥{_MIN_INST}inst):")
    for r in _RATIOS:
        test_ids = [i for i in fk_imgs if _score(id2img[i]["file_name"]) < r]
        ti = len(test_ids)
        tn = sum(len(boxes_by_img[i]) for i in test_ids)
        ok = ti >= _MIN_IMG and tn >= _MIN_INST
        print(f"  ratio {r:.2f}: test {ti}img / {tn}inst  train {len(fk_imgs)-ti}img  {'✓ 채택' if ok and chosen is None else ''}")
        if ok and chosen is None:
            chosen = r
    if chosen is None:
        print(f"\n⚠️ 최대 비율 {_RATIOS[-1]}에서도 미달 — 멈춤(보고 필요).")
        return

    # 채택 비율로 확정 분할
    test_ids = [i for i in fk_imgs if _score(id2img[i]["file_name"]) < chosen]
    train_ids = [i for i in fk_imgs if i not in set(test_ids)]
    test_names = sorted(id2img[i]["file_name"] for i in test_ids)
    train_names = sorted(id2img[i]["file_name"] for i in train_ids)

    # 평가셋 구축(test): 이미지 복사 + YOLO 라벨(class 0=forklift, 정규화)
    img_dir = _OUT / "images"; lab_dir = _OUT / "labels"
    if _OUT.exists():
        shutil.rmtree(_OUT)
    img_dir.mkdir(parents=True); lab_dir.mkdir(parents=True)
    total_box = 0
    for i in test_ids:
        im = id2img[i]; name = im["file_name"]; W, H = im["width"], im["height"]
        src = path_by_name.get(name)
        assert src is not None, f"이미지 없음: {name}"
        shutil.copy2(src, img_dir / name)
        lines = []
        for x, y, w, h in boxes_by_img[i]:
            cx, cy = (x + w / 2) / W, (y + h / 2) / H
            lines.append(f"0 {cx:.6f} {cy:.6f} {w/W:.6f} {h/H:.6f}")
            total_box += 1
        (lab_dir / (Path(name).stem + ".txt")).write_text("\n".join(lines) + "\n")
    (_OUT / "data.yaml").write_text("names:\n  0: forklift\n", encoding="utf-8")

    # box 수 assert(YOLO 라벨 총합 == 원본 forklift 박스 수)
    src_box = sum(len(boxes_by_img[i]) for i in test_ids)
    assert total_box == src_box, f"박스 수 불일치 {total_box} != {src_box}"

    # 네거티브(test 전용): forklift 0개 이미지 → hard(pallet_truck 등장) + 일반. 빈 라벨(forklift-negative).
    fk_set = set(fk_imgs)
    pt_ids = {a["image_id"] for a in d["annotations"] if a["category_id"] == _PALLET_TRUCK_CID}
    neg_all = set(id2img) - fk_set                       # forklift 0개(라벨 오염 방지)
    hard_pool = sorted(neg_all & pt_ids, key=lambda i: _score(id2img[i]["file_name"]))   # pallet_truck 등장
    gen_pool = sorted(neg_all - pt_ids, key=lambda i: _score(id2img[i]["file_name"]))    # 일반 창고
    n_hard = int(_NEG_TOTAL * _NEG_HARD_FRAC)
    neg_ids = hard_pool[:n_hard] + gen_pool[:_NEG_TOTAL - n_hard]
    neg_names = sorted(id2img[i]["file_name"] for i in neg_ids)
    for i in neg_ids:
        name = id2img[i]["file_name"]; src = path_by_name.get(name)
        assert src is not None, f"네거티브 이미지 없음: {name}"
        shutil.copy2(src, img_dir / name)
        (lab_dir / (Path(name).stem + ".txt")).write_text("", encoding="utf-8")   # 빈 라벨=forklift 없음
    n_hard_sel = len(hard_pool[:n_hard]); n_gen_sel = len(neg_ids) - n_hard_sel
    print(f"  네거티브 {len(neg_ids)}장(hard/pallet_truck {n_hard_sel} + 일반 {n_gen_sel})")

    _MANIFEST.write_text(json.dumps({
        "source": "LOCO loco-all-v1.json", "class": "forklift(id5)",
        "split": "SHA256 deterministic, test-priority", "ratio_test": chosen,
        "test_images_pos": len(test_ids), "test_instances": src_box,
        "train_images": len(train_ids),
        "negatives_total": len(neg_ids), "negatives_hard_pallet_truck": n_hard_sel,
        "negatives_general": n_gen_sel,
        "test_file_names": test_names, "train_file_names": train_names,
        "negative_file_names": neg_names,
        "t10b_no_inject": sorted(test_names + neg_names),   # 학습 유입 금지(test 오염 방지)
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n채택 비율 test={chosen:.2f}: positive {len(test_ids)}img/{src_box}inst + 네거티브 {len(neg_ids)}img · train {len(train_ids)}img")
    print(f"  평가셋: {img_dir.relative_to(_ROOT)} · 매니페스트 {_MANIFEST.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
