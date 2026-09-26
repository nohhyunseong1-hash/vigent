#!/usr/bin/env python3
"""scripts/train/finetune_rfdetr.py — PPE RF-DETR Nano 재학습(개발기 RTX 5070 Ti 로컬) + 학습 후 비교 하네스 자동 호출. [A-5, 2026-09-26]

★★ 실행 금지 상태(대표 지시): 이 스크립트는 작성만 됐고 한 번도 돌리지 않았다. `--dry-run` 만 허용.
   실제 학습은 대표 승인 뒤 — 그때도 아래 순서를 지킨다: 데이터 조립 검증 → 학습 → 하네스(전/후 비교) → 현장 정답지 판정.

무엇을 하는가
  1. 데이터 조립: 소스(우리 정답지 스키마 = labels/*.txt + images + split.json) 여러 개를 COCO 형식
     `out/dataset/{train,valid,test}/_annotations.coco.json` 으로 합친다(rfdetr 가 이 형식을 읽는다).
       · CSS v27(YOLO, data.yaml) · AI Hub 507/510 변환본(scripts/data/aihub_to_vigent.py 출력) · (나중에) 현장 정답지
       · **held-out 91장(benchmarks/results/v1_heldout_eval.json 의 heldout_files)은 어느 분할에도 넣지 않는다** — 하네스 "전/후" 비교 집합
       · 클래스는 config 의 `classes`(기본 person·Hardhat·NO-Hardhat·Safety-Vest·NO-Safety-Vest, Mask 제외)
  2. 학습: RFDETRNano(pretrain_weights=현 v1 또는 COCO nano).train(...) — 시드 고정, 체크포인트, resume.
  3. 학습 후: `scripts/eval/eval_v1_heldout.py --weights <best> --label <tag> [--dev74]` 자동 호출 → 전(v1)/후 비교표.
     현장 정답지는 하네스가 "미확보" 로 찍는다.

사용:
    python scripts/train/finetune_rfdetr.py --config configs/finetune_aihub_v2.yaml --dry-run    # 조립·계획만
    python scripts/train/finetune_rfdetr.py --config ... --epochs 30 --lr 1e-4 --out runs/finetune/aihub_v2  (★승인 후)
config 예:
    classes: [person, Hardhat, NO-Hardhat, Safety-Vest, NO-Safety-Vest]
    sources:
      - {name: css_v27, kind: yolo_yaml, path: data/datasets/css_safety/data.yaml, splits: {train: train, valid: valid}}
      - {name: aihub_507, kind: vigent, labels: D:/.../vigent_507/labels, images: D:/.../507_src, split: D:/.../vigent_507/split.json}
    exclude_files: benchmarks/results/v1_heldout_eval.json   # heldout_files 제외
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IMG_EXTS = (".jpg", ".jpeg", ".png")


def _img_size(p: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(p) as im:
        return im.width, im.height


def _read_yolo(txt: Path, names: list[str], classes: list[str]) -> list[tuple[int, list[float]]]:
    out = []
    for ln in txt.read_text(encoding="utf-8", errors="replace").splitlines():
        t = ln.split()
        if len(t) < 5:
            continue
        name = names[int(t[0])] if int(t[0]) < len(names) else None
        name = {"Safety Vest": "Safety-Vest", "NO-Safety Vest": "NO-Safety-Vest", "Person": "person"}.get(name, name)  # CSS 공백형 → 표준형
        if name not in classes:
            continue
        out.append((classes.index(name), [float(x) for x in t[1:5]]))
    return out


def collect_source(src: dict[str, Any], classes: list[str]) -> dict[str, list[tuple[Path, list[tuple[int, list[float]]]]]]:
    """소스 하나 → {split: [(이미지경로, [(cls, [cx,cy,w,h])])]}"""
    kind = src["kind"]
    out: dict[str, list] = {"train": [], "valid": []}
    if kind == "yolo_yaml":
        import yaml
        y = yaml.safe_load(Path(src["path"]).read_text(encoding="utf-8")); names = y["names"]
        base = Path(src["path"]).parent
        for split, sub in src.get("splits", {"train": "train", "valid": "valid"}).items():
            for img in sorted((base / sub / "images").glob("*")):
                if img.suffix.lower() not in IMG_EXTS:
                    continue
                lb = base / sub / "labels" / (img.stem + ".txt")
                out[split].append((img, _read_yolo(lb, names, classes) if lb.exists() else []))
    elif kind == "vigent":
        labels = Path(src["labels"]); images = Path(src["images"])
        names = (labels.parent / "classes.txt").read_text(encoding="utf-8").split() if (labels.parent / "classes.txt").exists() else classes
        idx = {p.stem: p for p in images.rglob("*") if p.suffix.lower() in IMG_EXTS}
        sp = json.loads(Path(src["split"]).read_text(encoding="utf-8"))
        for split, key in (("train", "train"), ("valid", "val")):
            for stem in sp[key]:
                if stem in idx:
                    out[split].append((idx[stem], _read_yolo(labels / f"{stem}.txt", names, classes)))
    else:
        raise ValueError(f"알 수 없는 kind: {kind}")
    return out


def build_coco(items: list[tuple[Path, list]], classes: list[str], dst: Path, copy: bool) -> dict[str, Any]:
    """rfdetr 가 읽는 COCO 폴더(dst/_annotations.coco.json + 이미지)를 만든다. 카테고리 id 는 1부터."""
    dst.mkdir(parents=True, exist_ok=True)
    images, anns = [], []
    stats = Counter()
    for i, (img, boxes) in enumerate(items, 1):
        W, H = _img_size(img)
        name = f"{img.stem}{img.suffix}"
        if copy:
            shutil.copy2(img, dst / name)
        images.append({"id": i, "file_name": name, "width": W, "height": H})
        for cls, (cx, cy, w, h) in boxes:
            anns.append({"id": len(anns) + 1, "image_id": i, "category_id": cls + 1,
                         "bbox": [round((cx - w / 2) * W, 2), round((cy - h / 2) * H, 2), round(w * W, 2), round(h * H, 2)],
                         "area": round(w * W * h * H, 2), "iscrowd": 0})
            stats[classes[cls]] += 1
    coco = {"images": images, "annotations": anns,
            "categories": [{"id": i + 1, "name": c, "supercategory": "ppe"} for i, c in enumerate(classes)]}
    (dst / "_annotations.coco.json").write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
    return {"images": len(images), "boxes": len(anns), "per_class": dict(stats)}


def assemble(cfg: dict[str, Any], out: Path, copy: bool) -> dict[str, Any]:
    classes = cfg["classes"]
    exclude = set()
    ex = cfg.get("exclude_files")
    if ex:
        j = json.loads((_ROOT / ex).read_text(encoding="utf-8"))
        exclude = {Path(f).stem for f in j.get("heldout_files", [])}
    merged: dict[str, list] = {"train": [], "valid": []}
    report: dict[str, Any] = {"sources": {}, "excluded_heldout": 0}
    for src in cfg["sources"]:
        got = collect_source(src, classes)
        for split in merged:
            kept = []
            for img, boxes in got[split]:
                if img.stem in exclude:
                    report["excluded_heldout"] += 1; continue
                kept.append((img, boxes))
            merged[split].extend(kept)
        report["sources"][src["name"]] = {s: len(v) for s, v in got.items()}
    # 누출 검사: 같은 stem 이 train·valid 양쪽에 있으면 실패
    ts = {i.stem for i, _ in merged["train"]}; vs = {i.stem for i, _ in merged["valid"]}
    if ts & vs:
        raise SystemExit(f"★누출: train·valid 양쪽에 같은 stem {len(ts & vs)}개 — 조립 중단")
    for split, items in merged.items():
        report[split] = build_coco(items, classes, out / "dataset" / split, copy)
    # rfdetr 는 test 폴더도 기대한다 — valid 를 그대로 복제(기준선 판정은 하네스가 별도로 한다)
    report["test"] = build_coco(merged["valid"], classes, out / "dataset" / "test", copy)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="조립 설정 yaml(classes·sources·exclude_files)")
    ap.add_argument("--out", default=str(_ROOT / "runs" / "finetune" / time.strftime("aihub_%Y%m%d_%H%M")))
    ap.add_argument("--epochs", type=int, default=30); ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2); ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--res", type=int, default=384, help="운용 해상도와 같게")
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--init", default=str(_ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"), help="시작 가중치(v1) — 'coco' 면 COCO nano")
    ap.add_argument("--label", default="", help="하네스 비교표의 '후' 열 이름(기본 out 폴더명)")
    ap.add_argument("--dev74", action="store_true", help="하네스에서 사고영상 dev 74 도 채점")
    ap.add_argument("--copy-images", action="store_true", help="이미지를 dataset/ 에 복사(기본은 복사 없이 계획만 — dry-run 용)")
    ap.add_argument("--dry-run", action="store_true", help="조립 통계·계획만 출력하고 학습하지 않는다")
    a = ap.parse_args()
    import yaml
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    random.seed(a.seed)
    try:
        import numpy as np
        import torch
        np.random.seed(a.seed)
        torch.manual_seed(a.seed)
    except Exception:  # noqa: BLE001
        pass

    rep = assemble(cfg, out, copy=a.copy_images and not a.dry_run)
    plan = {"config": a.config, "out": str(out), "epochs": a.epochs, "batch": a.batch, "grad_accum": a.grad_accum, "lr": a.lr,
            "res": a.res, "seed": a.seed, "init": a.init, "classes": cfg["classes"], "assembly": rep,
            "note": "held-out 91장은 제외됨(exclude_files) · 학습 후 eval_v1_heldout.py 로 전/후 비교 · 현장 정답지 미확보 → 하네스가 '미확보' 표기"}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    if a.dry_run:
        print("--dry-run: 학습하지 않았다(실행 금지 상태)")
        return 0

    # ── 학습(승인 후에만 도달) ──
    from rfdetr import RFDETRNano
    m = RFDETRNano(resolution=a.res) if a.init == "coco" else RFDETRNano(pretrain_weights=a.init, resolution=a.res)
    t0 = time.time()
    m.train(dataset_dir=str(out / "dataset"), epochs=a.epochs, batch_size=a.batch, grad_accum_steps=a.grad_accum, lr=a.lr,
            device="cuda", output_dir=str(out / "ckpt"), tensorboard=False, early_stopping=False, seed=a.seed)
    print(f"[train] done {(time.time() - t0) / 3600:.2f}h → {out / 'ckpt'}")
    best = next(iter(sorted((out / "ckpt").glob("checkpoint_best_total.pth"))), None) or next(iter(sorted((out / "ckpt").glob("checkpoint*.pth"))), None)
    if best is None:
        print("★체크포인트가 없다 — 학습 실패로 본다"); return 1
    # ── 하네스: 전(v1) / 후 비교 (held-out 91 · dev 74 · 현장 정답지 미확보) ──
    cmd = [sys.executable, str(_ROOT / "scripts" / "eval" / "eval_v1_heldout.py"), "--weights", str(best), "--label", a.label or out.name]
    if a.dev74:
        cmd.append("--dev74")
    print("[harness]", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(_ROOT), env={**os.environ})
    return rc


if __name__ == "__main__":
    sys.exit(main())
