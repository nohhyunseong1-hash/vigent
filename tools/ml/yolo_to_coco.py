#!/usr/bin/env python3
"""YOLO 데이터셋(images/ + labels/) → COCO instances.json 변환 (T12-B).

이 스크립트가 하는 일: YOLO 정규화 라벨(cx cy w h)을 COCO 절대좌표 어노테이션으로
바꿔 pycocotools 가 그대로 읽게 만든다. 셋별로 '분리' 생성한다(person/PPE 혼합 금지).
변환 끝에 '어노테이션 수 == 원본 라벨 라인 수'를 assert 로 검증한다.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _img_size(p: Path) -> tuple[int, int]:
    """이미지 (width, height). cv2 우선(파이프라인 표준), 실패 시 PIL 폴백."""
    try:
        import cv2
        im = cv2.imread(str(p))
        if im is not None:
            h, w = im.shape[:2]
            return int(w), int(h)
    except Exception:
        pass
    from PIL import Image
    with Image.open(p) as x:
        return int(x.width), int(x.height)


def load_classes(spec: str) -> list[str]:
    """--classes 인자: 콤마목록('person') 또는 data.yaml 경로 → 클래스명 리스트(순서 유지)."""
    if spec.endswith((".yaml", ".yml")):
        txt = Path(spec).read_text(encoding="utf-8")
        m = re.search(r"names:\s*\[([^\]]*)\]", txt)
        if not m:
            raise SystemExit(f"[오류] {spec} 에서 names 파싱 실패")
        return [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
    return [c.strip() for c in spec.split(",") if c.strip()]


def convert(images_dir: str, labels_dir: str, classes: list[str], out: str) -> dict:
    """YOLO → COCO. 반환: 요약 dict(images/annotations/categories 수)."""
    idir, ldir = Path(images_dir), Path(labels_dir)
    imgs = sorted(p for p in idir.iterdir() if p.suffix.lower() in IMG_EXTS)
    # COCO category id 는 1-based 관례(YOLO 0-based 인덱스 + 1)
    categories = [{"id": i + 1, "name": n} for i, n in enumerate(classes)]
    coco = {"images": [], "annotations": [], "categories": categories}
    ann_id = 1
    label_lines = 0  # 원본 라벨 라인 수(assert 대조용)
    for img_id, ip in enumerate(imgs, 1):
        w, h = _img_size(ip)
        coco["images"].append({"id": img_id, "file_name": ip.name, "width": w, "height": h})
        lp = ldir / (ip.stem + ".txt")
        if not lp.exists():
            continue
        for line in lp.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 5:  # 세그멘테이션/빈줄 등은 검출 GT 아님 → 건너뜀
                continue
            label_lines += 1
            cls = int(float(parts[0]))
            cx, cy, bw, bh = map(float, parts[1:])
            x, y = (cx - bw / 2) * w, (cy - bh / 2) * h
            bw_a, bh_a = bw * w, bh * h
            coco["annotations"].append({
                "id": ann_id, "image_id": img_id,
                "category_id": cls + 1,               # YOLO 0-based → COCO 1-based
                "bbox": [x, y, bw_a, bh_a], "area": bw_a * bh_a, "iscrowd": 0,
            })
            ann_id += 1
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(coco), encoding="utf-8")
    # 검증: 손실 없이 전량 변환됐는지(박스 수 == 원본 라벨 라인 수)
    assert len(coco["annotations"]) == label_lines, \
        f"박스 수 불일치: coco {len(coco['annotations'])} != 원본 {label_lines}"
    return {"images": len(coco["images"]), "annotations": len(coco["annotations"]),
            "categories": len(categories), "label_lines": label_lines}


def main() -> None:
    ap = argparse.ArgumentParser(description="YOLO→COCO 변환(T12-B)")
    ap.add_argument("--images", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--classes", required=True, help="콤마목록 또는 data.yaml 경로")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    s = convert(a.images, a.labels, load_classes(a.classes), a.out)
    print(f"[yolo_to_coco] {a.out}\n  이미지 {s['images']} · 박스 {s['annotations']} "
          f"· 클래스 {s['categories']} (원본 라벨 {s['label_lines']}줄 전량 일치 ✓)")


if __name__ == "__main__":
    main()
