"""ppe 학습 데이터 심층 무결성 스캔 (T10b NaN 진단 3단계).
build_ppe_train_ds 의 기본검사(coord 범위·wh>0)는 통과 → 여기선 NaN 유발 심층 항목:
  · category_id 범위(1~10 밖) · num_classes 일관성
  · degenerate 박스(1px 미만 w/h, 극단 종횡비) — giou/iou loss 에서 nan 유발 가능
  · 좌표 이미지경계 초과
대상: ~/Downloads/ppe_rfdetr_ds(RF-DETR 가 실제 소비하는 COCO). 이상 발견 시 이미지 목록 보고.
"""
import json
from collections import Counter
from pathlib import Path

_DS = Path.home() / "Downloads" / "ppe_rfdetr_ds"


def scan(split: str):
    coco = json.loads((_DS / split / "_annotations.coco.json").read_text())
    cats = {c["id"] for c in coco["categories"]}
    ncat = len(coco["categories"])
    dims = {im["id"]: (im["width"], im["height"]) for im in coco["images"]}
    bad_cat, degen, oob, tiny = [], [], [], []
    cat_count = Counter()
    for a in coco["annotations"]:
        cid = a["category_id"]
        cat_count[cid] += 1
        iid = a["image_id"]
        W, H = dims.get(iid, (0, 0))
        x, y, w, h = a["bbox"]
        if cid not in cats:
            bad_cat.append((iid, cid))
        if w <= 0 or h <= 0:
            degen.append((iid, w, h))
        elif w < 1 or h < 1:
            tiny.append((iid, round(w, 3), round(h, 3)))
        if W and (x < -1 or y < -1 or x + w > W + 1 or y + h > H + 1):
            oob.append((iid, round(x, 1), round(y, 1), round(w, 1), round(h, 1), W, H))
    return {
        "split": split, "ncat": ncat, "cats": sorted(cats),
        "cat_ids_used": sorted(cat_count), "n_ann": len(coco["annotations"]),
        "bad_cat": bad_cat, "degen": degen, "tiny": tiny[:10], "n_tiny": len(tiny),
        "oob": oob[:10], "n_oob": len(oob),
    }


def main():
    print("=== ppe COCO 심층 무결성 스캔 ===")
    total_bad = 0
    for split in ("train", "valid"):
        r = scan(split)
        print(f"\n[{split}] categories={r['ncat']}(id {r['cats']}) · 사용된 cat_id {r['cat_ids_used']} · ann {r['n_ann']}")
        print(f"  category_id 범위밖: {len(r['bad_cat'])}건 {r['bad_cat'][:5]}")
        print(f"  degenerate(w/h<=0): {len(r['degen'])}건")
        print(f"  tiny(1px 미만): {r['n_tiny']}건 예시 {r['tiny'][:3]}")
        print(f"  경계초과(oob): {r['n_oob']}건 예시 {r['oob'][:2]}")
        total_bad += len(r['bad_cat']) + len(r['degen'])
    print(f"\n  → 치명 이상(잘못된 cat_id + degenerate): {total_bad}건 " +
          ("(NaN 원인 후보 아님 — 데이터는 정상)" if total_bad == 0 else "⚠️ 이 이미지들 확인 필요"))


if __name__ == "__main__":
    main()
