#!/usr/bin/env python3
"""eval_v1_heldout.py — v1(ppe_rfdetr_v1.pth)의 **정직한 "전" 점수**. [T-0c, 2026-09-25]

★왜 있는가
  기존 "test 82 box mAP@50 75.62%" 는 valid/test 영상의 83~93% 가 train 에도 들어간 **누출 분할**에서 잰 값이다
  (docs/model/ppe_rfdetr_v1_provenance.md §3-1). 재학습 전후 비교표의 "전" 행은 **v1 이 한 번도 보지 않은 이미지**로 다시 재야 한다.

무엇을 하는가 (학습은 하지 않는다 — 기존 가중치를 새 분할로 평가만)
  1. held-out 구성: CSS v27 의 valid+test 이미지 중
       · 원본 stem 이 train 에 없고 · 유래 영상(`…_mp4`)이 train 에 없는 것만 (엄격 미노출)
       · 원본당 1장(증강본 제외 — valid/test 는 원래 1장이나 2장짜리 2개는 첫 장만)
     640×640 export 그대로 쓴다(v1 이 그 조건으로 학습됐다). 분할 파일 목록을 JSON 으로 남겨 재학습 비교에서 같은 집합을 쓴다.
  2. 추론: rfdetr predict, 해상도 384(배포 조건), 임계 0.05 로 전부 받아 AP 계산, P/R 은 앱 임계(tuning.yaml detect.conf.ppe, 현재 0.35).
  3. 지표: 클래스별 GT·TP·FP·FN·정밀도·재현율(IoU≥0.5, 클래스 일치, 1:1 매칭) + AP@50(전점 보간). 10클래스 전부 + 우리 4클래스 평균.

사용:
    python scripts/eval/eval_v1_heldout.py [--weights vigent-core/weights/ppe_rfdetr_v1.pth] [--res 384] [--out benchmarks/results/v1_heldout_eval.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

DS = _ROOT / "data" / "datasets" / "css_safety"
OUR4 = ["Hardhat", "NO-Hardhat", "Safety Vest", "NO-Safety Vest"]
_RF = re.compile(r"^(.*?)(?:_(?:jpg|jpeg|png|JPG|PNG))?\.rf\.[0-9a-f]{32}$")
_VID = re.compile(r"^(.*_mp4)-\d+$")


def stem_of(p: Path) -> str:
    m = _RF.match(p.stem)
    return m.group(1) if m else p.stem


def video_of(stem: str) -> str | None:
    m = _VID.match(stem)
    return m.group(1) if m else None


def build_heldout() -> tuple[list[Path], dict]:
    """엄격 미노출 집합 + 그 근거 수치."""
    train_stems: set[str] = set(); train_vids: set[str] = set()
    for p in (DS / "train" / "images").glob("*"):
        s = stem_of(p); train_stems.add(s)
        v = video_of(s)
        if v:
            train_vids.add(v)
    keep: list[Path] = []; seen: set[str] = set(); dropped = defaultdict(int)
    for split in ("valid", "test"):
        for p in sorted((DS / split / "images").glob("*")):
            s = stem_of(p); v = video_of(s)
            if s in train_stems:
                dropped["원본 stem 이 train 에 있음"] += 1; continue
            if v and v in train_vids:
                dropped["유래 영상이 train 에 있음"] += 1; continue
            if s in seen:
                dropped["같은 원본의 두 번째 증강본"] += 1; continue
            seen.add(s); keep.append(p)
    n_orig_all = len(train_stems | {stem_of(p) for sp in ("valid", "test") for p in (DS / sp / "images").glob("*")})
    info = {"heldout_images": len(keep), "heldout_unique_originals": len(seen), "all_unique_originals": n_orig_all,
            "heldout_share_of_originals": round(len(seen) / max(1, n_orig_all), 3),
            "valid_test_total": sum(1 for sp in ("valid", "test") for _ in (DS / sp / "images").glob("*")),
            "dropped": dict(dropped), "train_videos": len(train_vids)}
    return keep, info


def load_gt(img: Path, names: list[str]) -> list[tuple[str, list[float]]]:
    lb = img.parent.parent / "labels" / (img.stem + ".txt")
    out = []
    if not lb.exists():
        return out
    from PIL import Image
    with Image.open(img) as im:
        W, H = im.size
    for ln in lb.read_text(encoding="utf-8", errors="replace").splitlines():
        t = ln.split()
        if len(t) < 5:
            continue
        c = int(t[0]); cx, cy, w, h = (float(x) for x in t[1:5])
        out.append((names[c], [(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H]))
    return out


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def ap50(scored: list[tuple[float, bool]], n_gt: int) -> float:
    """전점 보간 AP@0.5. scored=(conf, is_tp) 전 검출."""
    if n_gt == 0:
        return float("nan")
    if not scored:
        return 0.0
    s = sorted(scored, key=lambda x: -x[0])
    tp = np.cumsum([1 if t else 0 for _, t in s]); fp = np.cumsum([0 if t else 1 for _, t in s])
    rec = tp / n_gt; prec = tp / np.maximum(tp + fp, 1e-9)
    mrec = np.concatenate([[0.0], rec, [1.0]]); mpre = np.concatenate([[0.0], prec, [0.0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def match(preds: list[tuple[str, list[float], float]], gts: list[tuple[str, list[float]]], thr: float) -> list[tuple[str, float, bool]]:
    """클래스별 1:1 그리디 매칭(conf 내림차순, IoU≥thr). 반환: (클래스, conf, TP?) — 전 검출."""
    used = [False] * len(gts); out = []
    for name, box, conf in sorted(preds, key=lambda x: -x[2]):
        best, bi = 0.0, -1
        for j, (gname, gbox) in enumerate(gts):
            if used[j] or gname != name:
                continue
            v = iou(box, gbox)
            if v > best:
                best, bi = v, j
        if bi >= 0 and best >= thr:
            used[bi] = True; out.append((name, conf, True))
        else:
            out.append((name, conf, False))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(_ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"))
    ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--out", default=str(_ROOT / "benchmarks" / "results" / "v1_heldout_eval.json"))
    ap.add_argument("--limit", type=int, default=0, help="시험용: 앞 N장만")
    a = ap.parse_args()
    import yaml
    names = yaml.safe_load((DS / "data.yaml").read_text(encoding="utf-8"))["names"]
    tun = yaml.safe_load((_ROOT / "config" / "tuning.yaml").read_text(encoding="utf-8"))
    op_conf = float(((tun.get("detect") or {}).get("conf") or {}).get("ppe", 0.35))

    imgs, info = build_heldout()
    if a.limit:
        imgs = imgs[: a.limit]
    print(f"held-out: {info['heldout_images']}장 / 고유 원본 {info['heldout_unique_originals']} / 전체 원본 {info['all_unique_originals']} "
          f"= {info['heldout_share_of_originals']:.1%} · 제외 {info['dropped']}")
    if info["heldout_share_of_originals"] < 0.20:
        print("★주의: held-out 이 전체 원본의 20% 미만이다 — 이것이 v1 이 안 본 이미지의 전부다(더 늘리면 train 원본이 섞인다)")

    import torch
    from PIL import Image
    from rfdetr import RFDETRNano
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = RFDETRNano(pretrain_weights=a.weights, device=dev, resolution=a.res)
    try:
        m.optimize_for_inference()
    except Exception:  # noqa: BLE001
        pass
    cls_names = list(getattr(m, "class_names", None) or names)
    # rfdetr 커스텀 체크포인트: class_id 는 0-indexed 로 class_names 에 대응(adapter 와 같은 규칙)
    n_gt: dict[str, int] = defaultdict(int); scored: dict[str, list] = defaultdict(list)
    op: dict[str, dict[str, int]] = {n: {"TP": 0, "FP": 0, "FN": 0} for n in names}
    t0 = time.time()
    for i, p in enumerate(imgs, 1):
        gts = load_gt(p, names)
        for g, _ in gts:
            n_gt[g] += 1
        det = m.predict(Image.open(p).convert("RGB"), threshold=0.05)
        preds = []
        for box, cid, conf in zip(det.xyxy, det.class_id, det.confidence):
            cid = int(cid)
            if 0 <= cid < len(cls_names):
                preds.append((cls_names[cid], [float(x) for x in box], float(conf)))
        for name, conf, tp in match(preds, gts, a.iou):
            scored[name].append((conf, tp))
        # 운용점 P/R: 임계 이상만으로 다시 매칭
        op_preds = [pr for pr in preds if pr[2] >= op_conf]
        res = match(op_preds, gts, a.iou)
        for name, _, tp in res:
            op[name]["TP" if tp else "FP"] += 1
        for gname in {g for g, _ in gts}:
            gt_c = sum(1 for g, _ in gts if g == gname)
            tp_c = sum(1 for n, _, tp in res if tp and n == gname)
            op[gname]["FN"] += gt_c - tp_c
        if i % 20 == 0:
            print(f"  {i}/{len(imgs)} ({time.time() - t0:.0f}s)")

    rows = []
    for n in names:
        tp, fp, fn = op[n]["TP"], op[n]["FP"], op[n]["FN"]
        prec = tp / (tp + fp) if tp + fp else float("nan"); rec = tp / (tp + fn) if tp + fn else float("nan")
        rows.append({"class": n, "gt": n_gt[n], "tp": tp, "fp": fp, "fn": fn,
                     "precision": None if np.isnan(prec) else round(prec * 100, 1),
                     "recall": None if np.isnan(rec) else round(rec * 100, 1),
                     "ap50": None if n_gt[n] == 0 else round(ap50(scored[n], n_gt[n]) * 100, 1)})
    def _mean(key, subset):
        v = [r[key] for r in rows if r["class"] in subset and r[key] is not None]
        return round(sum(v) / len(v), 1) if v else None
    summary = {"mAP50_all10": _mean("ap50", names), "mAP50_our4": _mean("ap50", OUR4),
               "recall_our4_mean": _mean("recall", OUR4), "precision_our4_mean": _mean("precision", OUR4)}
    print("\n| 클래스 | GT | TP | FP | FN | P% | R% | AP50% |\n|---|---|---|---|---|---|---|---|")
    for r in rows:
        mark = "**" if r["class"] in OUR4 else ""
        print(f"| {mark}{r['class']}{mark} | {r['gt']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['precision']} | {r['recall']} | {r['ap50']} |")
    print(f"| 우리 4클래스 평균 | | | | | {summary['precision_our4_mean']} | {summary['recall_our4_mean']} | **{summary['mAP50_our4']}** |")
    print(f"| 10클래스 mAP50 | | | | | | | {summary['mAP50_all10']} |")
    out = {"date": time.strftime("%Y-%m-%d %H:%M"), "weights": a.weights, "resolution": a.res, "op_conf": op_conf, "iou": a.iou,
           "device": dev, "heldout": info, "heldout_files": [str(p.relative_to(_ROOT)) for p in imgs],
           "rows": rows, "summary": summary, "elapsed_s": round(time.time() - t0, 1)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {a.out} · {len(imgs)}장 · {dev} · {out['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
