#!/usr/bin/env python3
"""scripts/eval/aihub_smoke_eval.py — 현재 배포 모델을 AI Hub 표본에 그대로 돌려 본 스모크 평가. [A-4, 2026-09-26]

★단서(결과 JSON 에도 박는다): **AI Hub 표본 기준 · 운용 조건 아님 · 기준선 아님.**
  · 표본 = 손에 있는 원천 이미지뿐: 510 VS_03_부가가치서비스(2,543장) · 507 개구부작업 경량 샘플(720장).
    507 미착용(공통 폴더) 원본은 미수신이라 **NO-Hardhat 은 측정 불가**.
  · 추론은 rfdetr predict(res 384, 임계 0.05 → AP50, 운용점 P/R 은 tuning.yaml 임계)이며 앱 파이프라인(ByteTrack·히스테리시스)이 아니다.
  · 기존 기준선(held-out 91 · 사고영상 74)은 건드리지 않는다.
  · 507 Hardhat GT 는 WO-01 상단 17% 파생([추정]) — 그 줄은 꼬리표를 단다.

사용:
    python scripts/eval/aihub_smoke_eval.py --out audit/aihub_smoke_20260926.json \
        --s510-images D:/vigent_private_data/aihub/_inspect/510_src_VS03 --s510-labels D:/vigent_private_data/aihub/_inspect/510_all \
        --s507-images D:/vigent_private_data/aihub/docs_507 --s507-labels D:/vigent_private_data/aihub/docs_507 [--limit 0]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "eval")); sys.path.insert(0, str(_ROOT / "scripts" / "data"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import aihub_to_vigent as A  # noqa: E402
from eval_v1_heldout import ap50, match, wilson  # noqa: E402

CAVEAT = "AI Hub 표본 기준 · 운용 조건 아님(앱 파이프라인·추적 없음) · 기준선 아님 — 기존 기준선(held-out 91·사고영상 74)은 수정하지 않는다"
WEIGHTS = {"person": None,   # COCO 사전학습 rf-detr-nano(운용 person 슬롯과 동일)
           "ppe": _ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth",
           "forklift": _ROOT / "vigent-core" / "weights" / "forklift_rfdetr_v1.pth"}


def class_names_of(model, coco: bool = False) -> dict[int, str]:
    """predict().class_id → 이름. ★COCO 사전학습 모델은 class_names 가 0-index 80개 list 인데 predict 는 **COCO id(1=person)** 를
    돌려준다(운용 어댑터 rfdetr_adapter.py:235-281 과 같은 분기 — 실측: 507 샘플 1장 예측 class_id=1, conf 0.95).
    커스텀 체크포인트는 자체 class_names(0-index) 그대로."""
    if coco:
        try:
            from rfdetr.assets.coco_classes import COCO_CLASSES
        except ImportError:  # 구버전
            from rfdetr.util.coco_classes import COCO_CLASSES
        return {int(k): str(v) for k, v in COCO_CLASSES.items()}
    cn = getattr(model, "class_names", None) or {}
    if isinstance(cn, dict):
        return {int(k): str(v) for k, v in cn.items()}
    return {i: str(n) for i, n in enumerate(cn)}


def load_model(kind: str, res: int):
    import torch
    from rfdetr import RFDETRNano
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    w = WEIGHTS[kind]
    m = RFDETRNano(resolution=res, device=dev) if w is None else RFDETRNano(pretrain_weights=str(w), resolution=res, device=dev)
    try:
        m.optimize_for_inference()
    except Exception:  # noqa: BLE001
        pass
    return m, dev


def gt_from_aihub(dataset: str, labels_root: Path, images_root: Path, hardhat_ratio: float | None = None):
    """이미지가 있는 stem 만 골라 (이미지경로, [(클래스명, [x1,y1,x2,y2] px)]) 목록을 만든다.
    ★hardhat_ratio 는 2026-09-26 파생 Hardhat 폐기로 무시된다(호환용 인자)."""
    imgs = {p.stem: p for p in images_root.rglob("*.jpg")}
    out = []
    for p in labels_root.rglob("*.json"):
        if p.stem not in imgs:
            continue
        fr = A.parse_frame(json.loads(p.read_text(encoding="utf-8")), dataset)
        W, H = fr["width"], fr["height"]
        boxes = []
        for b in A.convert_frame(fr, dataset, defaultdict(int)):
            cx, cy, w, h = b["box"]
            boxes.append((A.CLASSES[b["cls"]], [(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H], b["derived"]))
        out.append((imgs[p.stem], boxes))
    return sorted(out, key=lambda x: str(x[0]))


def evaluate(items, model, class_of, wanted: dict[str, float], iou_thr: float, verbose: bool = True) -> dict:
    """wanted = {우리 클래스명: 운용 임계}. class_of(cid)→우리 클래스명 또는 None."""
    from PIL import Image
    n_gt = defaultdict(int); scored = defaultdict(list); op = {c: {"TP": 0, "FP": 0, "FN": 0} for c in wanted}
    derived_gt = defaultdict(int); t0 = time.time()
    for i, (img, boxes) in enumerate(items, 1):
        gts = [(c, b) for c, b, _d in boxes if c in wanted]
        for c, b, d in boxes:
            if c in wanted:
                n_gt[c] += 1; derived_gt[c] += int(d)
        det = model.predict(Image.open(img).convert("RGB"), threshold=0.05)
        preds = []
        for box, cid, conf in zip(det.xyxy, det.class_id, det.confidence):
            name = class_of(int(cid))
            if name in wanted:
                preds.append((name, [float(x) for x in box], float(conf)))
        for name, conf, tp in match(preds, gts, iou_thr):
            scored[name].append((conf, tp))
        for c, thr in wanted.items():
            p_c = [p for p in preds if p[0] == c and p[2] >= thr]; g_c = [g for g in gts if g[0] == c]
            res = match(p_c, g_c, iou_thr)
            tp = sum(1 for _, _, t in res if t)
            op[c]["TP"] += tp; op[c]["FP"] += len(res) - tp; op[c]["FN"] += len(g_c) - tp
        if verbose and i % 200 == 0:
            print(f"  {i}/{len(items)} ({time.time() - t0:.0f}s)")
    rows = {}
    for c, thr in wanted.items():
        tp, fp, fn = op[c]["TP"], op[c]["FP"], op[c]["FN"]
        rows[c] = {"gt": n_gt[c], "gt_derived": derived_gt[c], "op_conf": thr, "tp": tp, "fp": fp, "fn": fn,
                   "precision": round(tp / (tp + fp) * 100, 1) if tp + fp else None, "precision_ci95": wilson(tp, tp + fp),
                   "recall": round(tp / (tp + fn) * 100, 1) if tp + fn else None, "recall_ci95": wilson(tp, tp + fn),
                   "ap50": round(ap50(scored[c], n_gt[c]) * 100, 1) if n_gt[c] else None}
    return {"images": len(items), "elapsed_s": round(time.time() - t0, 1), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_ROOT / "audit" / "aihub_smoke_20260926.json"))
    ap.add_argument("--s510-images", default=""); ap.add_argument("--s510-labels", default="")
    ap.add_argument("--s507-images", default=""); ap.add_argument("--s507-labels", default="")
    ap.add_argument("--res", type=int, default=384); ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0, help="시험용: 집합당 앞 N장")
    ap.add_argument("--hardhat-from-wo01", type=float, default=0.0, help="(폐기, 2026-09-26) 파생 Hardhat GT 는 더 만들지 않는다 — 인자는 무시")
    a = ap.parse_args()
    import yaml
    tun = yaml.safe_load((_ROOT / "config" / "tuning.yaml").read_text(encoding="utf-8"))
    conf = (tun.get("detect") or {}).get("conf") or {}
    thr = {"person": float(conf.get("person", 0.40)), "ppe": float(conf.get("ppe", 0.35)), "forklift": float(conf.get("forklift", 0.002))}
    result = {"date": time.strftime("%Y-%m-%d %H:%M"), "caveat": CAVEAT, "resolution": a.res, "iou": a.iou, "op_conf": thr, "sets": {}}

    if a.s510_images:
        items = gt_from_aihub("510", Path(a.s510_labels), Path(a.s510_images), None)
        if a.limit: items = items[: a.limit]
        print(f"[510 VS_03] 이미지+라벨 {len(items)}장")
        m, dev = load_model("person", a.res)
        cn = class_names_of(m, coco=True)
        print(f"  person 모델(COCO id 공간) {len(cn)}종, person id = {[k for k, v in cn.items() if v.lower() == 'person']}")
        r_person = evaluate(items, m, lambda cid: "person" if cn.get(cid, "").lower() == "person" else None, {"person": thr["person"]}, a.iou)
        m2, _ = load_model("forklift", a.res)
        r_fork = evaluate(items, m2, lambda cid: "forklift", {"forklift": thr["forklift"]}, a.iou)
        result["sets"]["510_VS03_부가가치서비스"] = {"device": dev, "person_model": "rf-detr-nano COCO(person 슬롯)", "forklift_model": "forklift_rfdetr_v1.pth",
                                               "person": r_person, "forklift": r_fork}
        print(json.dumps({"person": r_person["rows"], "forklift": r_fork["rows"]}, ensure_ascii=False, indent=1))

    if a.s507_images:
        items = gt_from_aihub("507", Path(a.s507_labels), Path(a.s507_images))
        if a.limit: items = items[: a.limit]
        print(f"[507 개구부 샘플] 이미지+라벨 {len(items)}장 (Hardhat GT 없음 — 파생 폐기(2026-09-26). Hardhat 행은 오탐 수만 의미)")
        m, dev = load_model("ppe", a.res)
        cn = class_names_of(m)
        print(f"  ppe 모델 class_names: {cn}")
        def ppe_name(cid):
            return {"Hardhat": "Hardhat", "NO-Hardhat": "NO-Hardhat", "Person": "person"}.get(cn.get(cid, ""))
        r_ppe = evaluate(items, m, ppe_name, {"Hardhat": thr["ppe"], "NO-Hardhat": thr["ppe"]}, a.iou)
        mp, _ = load_model("person", a.res)
        pcn = class_names_of(mp, coco=True)
        r_person = evaluate(items, mp, lambda cid: "person" if pcn.get(cid, "").lower() == "person" else None, {"person": thr["person"]}, a.iou)
        r_ppe["rows"]["NO-Hardhat"]["note"] = "측정 불가 — 507 미착용(공통 폴더) 원본 이미지 미수신(VS_03_공통 15GB). GT 0 이면 FP 만 센 것"
        r_ppe["rows"]["Hardhat"]["note"] = "GT 없음(파생 Hardhat 2026-09-26 폐기) — 이 행은 검출 수(=오탐으로 집계)만 의미. Hardhat 양성은 pseudo_hardhat.py 준라벨로"
        result["sets"]["507_개구부_샘플"] = {"device": dev, "ppe_model": "ppe_rfdetr_v1.pth", "person_model": "rf-detr-nano COCO",
                                          "ppe": r_ppe, "person": r_person}
        print(json.dumps({"ppe": r_ppe["rows"], "person": r_person["rows"]}, ensure_ascii=False, indent=1))

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out} ({out.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
