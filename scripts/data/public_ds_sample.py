#!/usr/bin/env python3
"""scripts/data/public_ds_sample.py — 공개 데이터셋 zip 에서 표본 N장을 뽑아 (1) 격자(contact sheet) 이미지 (2) 클래스별 박스 높이/이미지 높이 비 p10·p50·p90 (3) 해상도 분포를 낸다. [2026-09-27]

지원 형식: Roboflow COCO export(zip 안 train/valid/test/_annotations.coco.json) · Pascal VOC(zip 안 Annotations/*.xml + JPEGImages/*.jpg).
표본은 seed 고정 무작위(전 분할 합쳐서). 격자는 6열, 썸네일 320×180, 박스는 클래스별 색으로 그린다(시점 육안 판정용).
사용: python scripts/data/public_ds_sample.py <zip> --n 200 --out-dir audit/public_ppe/<name> --tag <name>
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import random
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COLORS = [(255, 60, 60), (60, 220, 60), (80, 140, 255), (255, 200, 0), (255, 0, 255), (0, 220, 220), (255, 130, 0), (200, 200, 200)]


def q(v: list[float]) -> dict | None:
    if not v:
        return None
    v = sorted(v); n = len(v)
    return {"n": n, "p10": round(v[int(n * .1)], 3), "p50": round(v[n // 2], 3), "p90": round(v[min(n - 1, int(n * .9))], 3)}


def load_index(z: zipfile.ZipFile) -> tuple[dict[str, list[tuple[str, list[float]]]], str]:
    """이미지 경로 → [(클래스명, [x1,y1,x2,y2])]. 형식 자동 판별."""
    names = z.namelist(); idx: dict[str, list] = {}
    cocos = [n for n in names if n.endswith("_annotations.coco.json")]
    if cocos:
        for cj in cocos:
            j = json.loads(z.read(cj)); base = cj.rsplit("/", 1)[0] + "/" if "/" in cj else ""
            cats = {c["id"]: c["name"] for c in j["categories"]}; imgs = {im["id"]: im["file_name"] for im in j["images"]}
            for im in j["images"]:
                idx.setdefault(base + im["file_name"], [])
            for a in j["annotations"]:
                x, y, w, h = a["bbox"]; idx[base + imgs[a["image_id"]]].append((cats[a["category_id"]], [x, y, x + w, y + h]))
        return idx, "coco"
    xmls = [n for n in names if n.lower().endswith(".xml") and "/Annotations/" in n]
    if xmls:
        jpgs = {n.rsplit("/", 1)[-1].rsplit(".", 1)[0]: n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png"))}
        for xn in xmls:
            stem = xn.rsplit("/", 1)[-1][:-4]
            if stem not in jpgs:
                continue
            root = ET.fromstring(z.read(xn)); anns = []
            for o in root.iter("object"):
                bb = o.find("bndbox"); nm = o.findtext("name")
                if bb is not None:
                    anns.append((nm, [float(bb.findtext(t)) for t in ("xmin", "ymin", "xmax", "ymax")]))
            idx[jpgs[stem]] = anns
        return idx, "voc"
    raise SystemExit("지원하지 않는 형식(COCO json / VOC xml 없음)")


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("zip"); ap.add_argument("--n", type=int, default=30); ap.add_argument("--out-dir", required=True); ap.add_argument("--tag", required=True); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(); z = zipfile.ZipFile(a.zip); idx, fmt = load_index(z)
    keys = sorted(idx); random.seed(a.seed); picks = keys if len(keys) <= a.n else random.sample(keys, a.n)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    cls_all = collections.Counter(c for v in idx.values() for c, _ in v)
    res = collections.Counter(); ratio = collections.defaultdict(list); px = collections.defaultdict(list); asp = collections.defaultdict(list); thumbs = []
    cmap = {c: COLORS[i % len(COLORS)] for i, c in enumerate(sorted(cls_all))}
    for k in picks:
        try:
            im = Image.open(io.BytesIO(z.read(k))).convert("RGB")
        except Exception:
            continue
        W, H = im.size; res[f"{W}x{H}"] += 1; dr = ImageDraw.Draw(im)
        for c, (x1, y1, x2, y2) in idx[k]:
            if y2 > y1 and x2 > x1:
                ratio[c].append((y2 - y1) / H); px[c].append(y2 - y1); asp[c].append((x2 - x1) / (y2 - y1))
            dr.rectangle((x1, y1, x2, y2), outline=cmap.get(c, (255, 255, 255)), width=max(2, W // 400))
        t = im.copy(); t.thumbnail((320, 180)); tile = Image.new("RGB", (320, 180), (20, 20, 20)); tile.paste(t, ((320 - t.width) // 2, (180 - t.height) // 2))
        ImageDraw.Draw(tile).text((3, 3), f"{k.rsplit('/', 1)[-1][:28]} {W}x{H}", fill=(255, 255, 0)); thumbs.append(tile)
    cols = 6; per = 15 * cols; sheets = []
    for s in range(0, len(thumbs), per):
        part = thumbs[s:s + per]; rows = (len(part) + cols - 1) // cols; sheet = Image.new("RGB", (cols * 320, rows * 180), (0, 0, 0))
        for i, t in enumerate(part):
            sheet.paste(t, ((i % cols) * 320, (i // cols) * 180))
        p = out / f"_contact_{a.tag}_{s // per + 1}.jpg"; sheet.save(p, quality=80); sheets.append(str(p))
    legend = ", ".join(f"{c}={cmap[c]}" for c in sorted(cmap))
    summary = {"zip": a.zip, "format": fmt, "images_total": len(keys), "sampled": len(thumbs), "seed": a.seed, "classes_total_boxes": dict(cls_all),
               "sample_resolution": dict(res.most_common()), "box_h_over_img_h": {c: q(v) for c, v in sorted(ratio.items())},
               "box_h_px": {c: q(v) for c, v in sorted(px.items())}, "box_aspect": {c: q(v) for c, v in sorted(asp.items())}, "sheets": sheets, "legend": legend}
    (out / f"_summary_{a.tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("format", "images_total", "sampled", "classes_total_boxes", "sample_resolution", "box_h_over_img_h")}, ensure_ascii=False))
    print("legend:", legend); print("sheets:", sheets); return 0


if __name__ == "__main__":
    sys.exit(main())
