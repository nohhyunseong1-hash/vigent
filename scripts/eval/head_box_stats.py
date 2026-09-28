#!/usr/bin/env python3
"""scripts/eval/head_box_stats.py — 머리 박스(Hardhat/NO-Hardhat) 높이(px) 분포를 4집단으로 비교한다. [2026-09-27 결정 ②]

집단: 507 train(vigent_507 변환본, 1920×1080) · CSS train(640×640) · held-out 91(CSS, 640×640) · dev74(현장 사고영상 프레임, 원본 크기).
높이 = 정규화 h × 이미지 높이(px). 이미지 크기는 실제 파일에서 읽는다(가정 없음).
사용: python scripts/eval/head_box_stats.py [--out audit/head_box_stats.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval")); sys.path.insert(0, str(_ROOT / "benchmarks")); sys.path.insert(0, str(_ROOT / "vigent-core"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEAD = {"Hardhat", "NO-Hardhat"}


def _q(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs); n = len(s)
    return {"n": n, "p10": round(s[int(n * 0.1)], 1), "p50": round(s[n // 2], 1), "p90": round(s[min(n - 1, int(n * 0.9))], 1),
            "min": round(s[0], 1), "max": round(s[-1], 1)}


def heights_yolo(label_files: list[Path], names: list[str], img_of, cache: dict) -> list[float]:
    from PIL import Image
    out = []
    for lb in label_files:
        img = img_of(lb)
        if img is None or not img.exists():
            continue
        if img not in cache:
            with Image.open(img) as im:
                cache[img] = im.size
        _w, h_img = cache[img]
        for ln in lb.read_text(encoding="utf-8", errors="replace").splitlines():
            t = ln.split()
            if len(t) < 5:
                continue
            ci = int(t[0]); name = names[ci] if ci < len(names) else ""
            if name in HEAD:
                out.append(float(t[4]) * h_img)
                REL.setdefault(id(label_files), []).append(float(t[4]) * 384.0)   # 모델 입력(384 정사각) 기준 px — 해상도가 다른 집단을 같은 잣대로
    return out


REL: dict = {}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(_ROOT / "audit" / "head_box_stats.json")); a = ap.parse_args()
    import yaml
    res = {}; cache: dict = {}
    # 1) 507 train
    import data_paths as _dp
    v507 = _dp.media("aihub/vigent_507"); names507 = (v507 / "classes.txt").read_text(encoding="utf-8").split()
    sp = json.loads((v507 / "split.json").read_text(encoding="utf-8"))
    idx = {p.stem: p for p in _dp.media("aihub/_inspect/507_src").rglob("*.jpg")}
    files = [v507 / "labels" / f"{s}.txt" for s in sp["train"]]
    res["507_train(WO-04 머리 박스)"] = _q(heights_yolo(files, names507, lambda lb: idx.get(lb.stem), cache))
    # 2) CSS train / 3) held-out 91
    css = _ROOT / "data" / "datasets" / "css_safety"; names_css = yaml.safe_load((css / "data.yaml").read_text(encoding="utf-8"))["names"]
    tr = sorted((css / "train" / "labels").glob("*.txt"))
    res["CSS_train"] = _q(heights_yolo(tr, names_css, lambda lb: css / "train" / "images" / (lb.stem + ".jpg"), cache))
    import eval_v1_heldout as H
    imgs, _info = H.build_heldout("video")
    def _lb_for(img: Path) -> Path:
        return img.parent.parent / "labels" / (img.stem + ".txt")
    ho_labels = [_lb_for(p) for p in imgs]; ho_img = {_lb_for(p): p for p in imgs}
    res["held-out_91"] = _q(heights_yolo(ho_labels, names_css, lambda lb: ho_img.get(lb), cache))
    # 4) dev74
    import x4b_score_candidates as x4b
    names_fe = x4b.CLASSES
    dev_files = x4b.SPLIT["dev"]
    frames = x4b.FRAMES_DIR; labels = x4b.LABELS_DIR
    lbs = [labels / (Path(f).stem + ".txt") for f in dev_files]
    def _img_fe(lb: Path):
        for ext in (".jpg", ".png", ".jpeg"):
            p = frames / (lb.stem + ext)
            if p.exists():
                return p
        return None
    res["dev74(현장 사고영상)"] = _q(heights_yolo(lbs, names_fe, _img_fe, cache))
    res["note"] = "abs = 정규화 h × 실제 이미지 높이(px): 507 1920×1080 · CSS/held-out 640×640(리사이즈본) · dev74 원본 프레임. rel384 = 정규화 h × 384(모델 입력 기준 px — 집단 간 비교는 이것으로)"
    rel_lists = list(REL.values())   # heights_yolo 호출 순서와 같다(507, CSS, held-out, dev74)
    keys = [k for k, v in res.items() if isinstance(v, dict) and "n" in v]
    for k, lst in zip(keys, rel_lists):
        res[k]["rel384"] = _q(lst)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("| 집단 | n | abs p10 | abs p50 | abs p90 | rel384 p10 | **rel384 p50** | rel384 p90 |"); print("|---|---|---|---|---|---|---|---|")
    for k in keys:
        v = res[k]; r = v.get("rel384", {})
        if v.get("n"):
            print(f"| {k} | {v['n']} | {v['p10']} | {v['p50']} | {v['p90']} | {r.get('p10')} | **{r.get('p50')}** | {r.get('p90')} |")
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
