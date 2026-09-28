#!/usr/bin/env python3
"""scripts/data/field_fixture.py — 현장 경로 dry-run·테스트용 **합성** 자료(얼굴 없음). 회색 배경에 사각형만 그린 이미지 + 라벨 + 분할 + held-out. [2026-09-27]

두 가지를 만든다:
  raw   : field_prelabel 입력 흉내 — 카메라 폴더 2개에 짧은 mp4 1개씩 + 사진 2장(날짜·주야를 이름에 넣음)
  vigent: finetune_rfdetr 의 vigent 소스 형태 — images/·labels/·classes.txt·split.json·heldout.json·manifest.json (field_prelabel+field_split 산출 흉내)
사용: python scripts/data/field_fixture.py --out D:/vigent_private_data/field/_fixture_dryrun [--cams 2 --clips 3 --frames 20]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_VC = str(Path(__file__).resolve().parents[2] / "vigent-core")
if _VC not in sys.path:
    sys.path.insert(0, _VC)
from labels import STD5  # noqa: E402  [CODE_AUDIT B-5] 클래스 정본

CLASSES = list(STD5)


def _img(W: int, H: int, boxes: list[tuple[int, list[int]]], seed: int):
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    im = Image.new("RGB", (W, H), (rnd.randint(60, 120),) * 3); dr = ImageDraw.Draw(im)
    for c, (x1, y1, x2, y2) in boxes:
        dr.rectangle((x1, y1, x2, y2), outline=[(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)][c], width=3)
    return im


def make_raw(out: Path, cams: int = 2, seconds: int = 3, fps: int = 10) -> list[Path]:
    """카메라 폴더마다 mp4 1개(seconds×fps 프레임) + 사진 2장. 이름에 날짜·주야를 넣는다."""
    import cv2
    import numpy as np
    made = []
    for ci in range(cams):
        d = out / f"cam{ci + 1}_test"; d.mkdir(parents=True, exist_ok=True)
        dn = "day" if ci % 2 == 0 else "night"
        vp = d / f"2026100{ci + 1}_1{ci}0000_{dn}_A.mp4"
        vw = cv2.VideoWriter(str(vp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
        for k in range(seconds * fps):
            fr = np.full((240, 320, 3), 90 + (k % 20), dtype=np.uint8); cv2.rectangle(fr, (40 + k, 60), (100 + k, 200), (0, 0, 255), 2)
            vw.write(fr)
        vw.release(); made.append(vp)
        for j in range(2):
            p = d / f"2026100{ci + 1}_2{j}0000_{dn}_{j}.jpg"
            _img(320, 240, [(0, [50, 40, 120, 200])], j).save(p, quality=90); made.append(p)
    return made


def make_vigent(out: Path, cams: int = 2, clips: int = 3, frames: int = 20, seed: int = 0, heldout_n: int = 12) -> dict:
    """field_prelabel + field_split 산출 흉내. 카메라 cams × 주야 2 × 클립 clips × 프레임 frames. 마지막 카메라가 valid."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from field_split import select_heldout, split_cameras
    rnd = random.Random(seed)
    for sub in ("images", "labels", "labels_meta", "negatives"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    fr_list = []
    for ci in range(cams):
        cam = f"cam{ci + 1}"
        for dn in ("day", "night"):
            for k in range(clips):
                clip = f"{cam}/2026100{ci + 1}_{dn}_{k}"
                for f in range(frames):
                    stem = f"{cam}__2026100{ci + 1}__{dn}__{dn}_{k}__f{f * 5:06d}"
                    negative = f % 5 == 4
                    W, H = 320, 240
                    boxes = [] if negative else [(0, [40 + f, 40, 110 + f, 200]), (rnd.choice([1, 2]), [55 + f, 40, 95 + f, 70]), (rnd.choice([3, 4]), [45 + f, 80, 105 + f, 150])]
                    _img(W, H, boxes, f).save(out / ("negatives" if negative else "images") / f"{stem}.jpg", quality=85)
                    if not negative:
                        (out / "labels" / f"{stem}.txt").write_text("".join(f"{c} {(b[0] + b[2]) / 2 / W:.6f} {(b[1] + b[3]) / 2 / H:.6f} {(b[2] - b[0]) / W:.6f} {(b[3] - b[1]) / H:.6f}\n" for c, b in boxes), encoding="utf-8")
                    fr_list.append({"stem": stem, "camera": cam, "date": f"2026100{ci + 1}", "daynight": dn, "clip": clip, "negative": negative,
                                    "n_person": 0 if negative else 1, "n_boxes": len(boxes), "frame_idx": f * 5, "source_file": "fixture"})
    manifest = {"created": "fixture", "classes": CLASSES, "conf": 0.4, "target_fps": 2.0, "frames": fr_list, "counts": {"positive": sum(1 for f in fr_list if not f["negative"]), "negative": sum(1 for f in fr_list if f["negative"])}}
    h = select_heldout(fr_list, heldout_n, seed)
    hs = set(h["frames"]) | set(h["negatives"])
    for f in fr_list:
        f["heldout"] = f["stem"] in hs; f["no_train"] = f["stem"] in hs
    (out / "heldout.json").write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    split, problems = split_cameras(fr_list, hs, 0.25, seed, val_cameras=[f"cam{cams}"])
    if problems:
        raise SystemExit(f"fixture 분할 실패: {problems}")
    (out / "split.json").write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"frames": len(fr_list), "positive": manifest["counts"]["positive"], "heldout_pos": h["n_positive"], "heldout_neg": h["n_negative"],
            "train": len(split["train"]), "val": len(split["val"])}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--cams", type=int, default=2)
    ap.add_argument("--clips", type=int, default=3); ap.add_argument("--frames", type=int, default=20); ap.add_argument("--no-raw", action="store_true")
    a = ap.parse_args(); out = Path(a.out)
    if not a.no_raw:
        made = make_raw(out / "raw", a.cams); print(f"raw: {len(made)} 파일 → {out / 'raw'}")
    r = make_vigent(out / "prelabel", a.cams, a.clips, a.frames); print("vigent:", json.dumps(r), "→", out / "prelabel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
