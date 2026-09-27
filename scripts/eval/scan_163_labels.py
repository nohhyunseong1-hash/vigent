#!/usr/bin/env python3
"""scripts/eval/scan_163_labels.py — AI Hub 163(공사현장 안전장비 인식) 라벨 zip 을 **풀지 않고** 전수 집계한다. [A-1 형식, 2026-09-27]

라벨 JSON 1장 = 이미지 1장: image{filename, path, resolution[w,h], location, date} · annotations[]{class(코드), middle classification, box[x1,y1,x2,y2], Instance_id}.
클래스 **이름은 JSON 에 없다** — 코드만 센다(이름 대응은 AI Hub 메타데이터 구조표로 별도 확인).
집계: 클래스 코드별 박스 수·이미지 수 · middle classification × class · 폴더(현장/촬영 대상 카테고리)별 · 박스 높이 px/이미지 높이 비 분위수 ·
      해상도 분포 · 이미지당 박스 수 · 같은 이미지에서 함께 나오는 코드 쌍 상위.
사용: python scripts/eval/scan_163_labels.py <zip> --out <json>
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def q(v: list[float]) -> dict | None:
    if not v:
        return None
    v = sorted(v); n = len(v)
    return {"n": n, "p10": round(v[int(n * .1)], 3), "p25": round(v[int(n * .25)], 3), "median": round(v[n // 2], 3),
            "p75": round(v[int(n * .75)], 3), "p90": round(v[min(n - 1, int(n * .9))], 3)}


def decode_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("cp949")
    except Exception:
        return name


def scan(zpath: Path) -> dict:
    z = zipfile.ZipFile(zpath)
    cls_box = collections.Counter(); cls_img = collections.Counter(); mid_cls = collections.Counter()
    folder_cat = collections.Counter(); folder_cat_cls = collections.defaultdict(collections.Counter)
    site = collections.Counter()
    h_px = collections.defaultdict(list); w_px = collections.defaultdict(list); h_ratio = collections.defaultdict(list); asp = collections.defaultdict(list)
    res = collections.Counter(); per_img = []; pairs = collections.Counter(); bad = 0; imgs = 0; bad_box = 0
    for info in z.infolist():
        if not info.filename.lower().endswith(".json"):
            continue
        imgs += 1
        try:
            j = json.loads(z.read(info))
        except Exception:
            bad += 1; continue
        parts = decode_name(info.filename).split("/")
        s = parts[1] if len(parts) > 2 else "?"; cat = parts[2] if len(parts) > 3 else "?"
        site[s] += 1; folder_cat[cat] += 1
        W, H = (j.get("image", {}).get("resolution") or [0, 0])[:2]
        res[f"{W}x{H}"] += 1
        anns = j.get("annotations", []); per_img.append(len(anns)); present = set()
        for a in anns:
            c = str(a.get("class")); m = str(a.get("middle classification"))
            cls_box[c] += 1; mid_cls[(m, c)] += 1; folder_cat_cls[cat][c] += 1; present.add(c)
            b = a.get("box") or []
            if len(b) == 4 and H > 0:
                bw, bh = b[2] - b[0], b[3] - b[1]
                if bw <= 0 or bh <= 0:
                    bad_box += 1; continue
                h_px[c].append(bh); w_px[c].append(bw); h_ratio[c].append(bh / H); asp[c].append(bw / bh)
        for c in present:
            cls_img[c] += 1
        pl = sorted(present)
        for i in range(len(pl)):
            for k in range(i + 1, len(pl)):
                pairs[(pl[i], pl[k])] += 1
    return {"zip": str(zpath), "images": imgs, "bad_json": bad, "bad_box": bad_box, "boxes": sum(cls_box.values()),
            "boxes_per_image": q(per_img), "images_with_no_box": sum(1 for n in per_img if n == 0),
            "class_boxes": dict(sorted(cls_box.items())), "class_images": dict(sorted(cls_img.items())),
            "middle_x_class": {f"{m}|{c}": n for (m, c), n in sorted(mid_cls.items())},
            "folder_category_images": dict(folder_cat), "folder_category_class": {k: dict(sorted(v.items())) for k, v in folder_cat_cls.items()},
            "site_images": dict(site), "resolution": dict(res.most_common()),
            "box_h_px": {c: q(v) for c, v in sorted(h_px.items())}, "box_w_px": {c: q(v) for c, v in sorted(w_px.items())},
            "box_h_over_img_h": {c: q(v) for c, v in sorted(h_ratio.items())}, "box_aspect_w_over_h": {c: q(v) for c, v in sorted(asp.items())},
            "cooccur_pairs_top": [[list(k), n] for k, n in pairs.most_common(20)]}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("zip"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = scan(Path(a.zip))
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("images", "bad_json", "bad_box", "boxes", "class_boxes", "class_images", "folder_category_images", "resolution", "boxes_per_image")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
