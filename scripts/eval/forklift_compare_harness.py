#!/usr/bin/env python3
"""scripts/eval/forklift_compare_harness.py — forklift 검출기 전/후 비교 하네스. [2026-09-26, 재학습 1순위 = forklift(510)]

두 집합
  ① 510 held-out(장소 단위 val, `scripts/data/aihub_to_vigent.py --dataset 510` 의 split.json) — **판정 집합**
     AP50 · 운용점(conf 0.5) P/R[Wilson95] · 이미지 단위: 양성 검출률 / **음성 오탐률**(지게차 없는 이미지에서 conf≥0.5 박스 ≥1개인 비율)
  ② 8/27 학원 overlay 956프레임 — **참고 집합**(정답 = 장면 대본, 원본 미보존, 박스가 그려진 표시용 영상)
     현장 YOLO 박스와 IoU≥0.5 일치율(conf≥0.5 / ≥0.1) · ≥1 박스 비율

행
  전   = forklift_rfdetr_v1(같은 집합에서 `--write-baseline` 으로 잰 값. 없으면 "미측정" + 2026-09-26 스모크 수치를 [참고] 로)
  후   = --weights
  참고 = forklift_boda_ax YOLO(AGPL — **후보 아님**, 라이선스상 배포 불가) 학원 대본 대비 97.7% · present 98.1%

목표(2026-09-26 선언, GOALS_FK): 510 held-out **AP50 ≥ 70%** · 음성 오탐률(conf≥0.5) **≤ 1%/장**. 학원 집합에는 목표 없음(참고).

사용:
    python scripts/eval/forklift_compare_harness.py --weights vigent-core/weights/forklift_rfdetr_v1.pth --label v1 --write-baseline
    python scripts/eval/forklift_compare_harness.py --weights runs/finetune/fk_510/ckpt/checkpoint_best_total.pth --label fk_510
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from eval_v1_heldout import ap50, iou, match, wilson  # noqa: E402

GOALS_FK = {
    "ap50_min": 70.0, "neg_fp_rate_max": 1.0, "op_conf": 0.5,
    "note": "510 held-out(장소 단위) AP50 ≥ 70 · 지게차 없는 이미지에서 conf≥0.5 박스 ≤ 1%/장 (2026-09-26 선언). 학원 956 은 참고",
}
BODA_REF = {
    "model": "forklift_boda_ax (YOLO, AGPL — 후보 아님·참고 열)", "field_script_rate": 97.7, "field_script_frac": "908/929",
    "field_present_rate": 98.1, "source": "benchmarks/field_academy_2026-08-27.md:32 · audit/forklift_field_rerun_20260926.json",
}
V1_SMOKE_NOTE = ("같은 집합 기준선 아님 — 2026-09-26 스모크(510 VS_03 2,543장): AP50 0.0 · R 23.6 @0.002 · 음성 2,399장 중 91.4% 가 conf≥0.5 박스 · "
                 "학원 956 IoU 일치 0.0% @0.5 (`docs/model/ppe_rfdetr_v1_provenance.md` §9-4)")
BASELINE_JSON = _ROOT / "benchmarks" / "results" / "forklift_v1_baseline.json"
FIELD_ROOT_DEFAULT = r"D:\vigent_field\20260827\field_20260827"
IMG_EXTS = (".jpg", ".jpeg", ".png")


# ---------------------------------------------------------------------------------------------------------------------
# 순수 계산(테스트 대상) — predict 는 주입
# ---------------------------------------------------------------------------------------------------------------------
def eval_510(items: list[tuple[Any, list[list[float]]]], predict: Callable[[Any], list[tuple[list[float], float]]],
             op_conf: float = 0.5, iou_thr: float = 0.5) -> dict[str, Any]:
    """items=[(키, [GT xyxy px, ...])], predict(키)→[(xyxy px, conf), ...](임계 0.001 전 검출). forklift 단일 클래스."""
    scored: list[tuple[float, bool]] = []
    n_gt = tp = fp = fn = 0
    pos = neg = pos_hit = neg_fa = neg_fa03 = 0
    for key, gts in items:
        preds = predict(key)
        n_gt += len(gts)
        res = match([("forklift", b, c) for b, c in preds], [("forklift", g) for g in gts], iou_thr)
        scored.extend((c, t) for _, c, t in res)
        op = [r for r in res if r[1] >= op_conf]; t = sum(1 for r in op if r[2])
        tp += t; fp += len(op) - t; fn += len(gts) - t
        mc = max((c for _, c in preds), default=0.0)
        if gts:
            pos += 1; pos_hit += int(mc >= op_conf)
        else:
            neg += 1; neg_fa += int(mc >= op_conf); neg_fa03 += int(mc >= 0.3)
    r = lambda k, n: round(k / n * 100, 1) if n else None  # noqa: E731
    w = lambda k, n: [round(x * 100, 1) for x in wilson(k, n)] if n else None  # noqa: E731
    return {"images": len(items), "gt": n_gt, "ap50": round(ap50(scored, n_gt) * 100, 1) if n_gt else None,
            "op_conf": op_conf, "tp": tp, "fp": fp, "fn": fn,
            "precision": r(tp, tp + fp), "precision_ci95": w(tp, tp + fp), "recall": r(tp, tp + fn), "recall_ci95": w(tp, tp + fn),
            "pos_images": pos, "neg_images": neg, "pos_detect_rate": r(pos_hit, pos),
            "neg_fp_rate": r(neg_fa, neg), "neg_fp_rate_ci95": w(neg_fa, neg), "neg_fp_rate_03": r(neg_fa03, neg)}


def eval_field_frames(frames: list[tuple[Any, list[list[float]]]], predict: Callable[[Any], list[tuple[list[float], float]]],
                      op_conf: float = 0.5) -> dict[str, Any]:
    """frames=[(키, [현장 YOLO 지게차 박스 xyxy px, ...])]. 참고 집합 — 정답은 대본이므로 '일치율'로만 읽는다."""
    n = len(frames); ref = agree05 = agree01 = any05 = 0
    for key, boda in frames:
        preds = predict(key)
        mc = max((c for _, c in preds), default=0.0); any05 += int(mc >= op_conf)
        if boda:
            ref += 1
            best = max((c for b, c in preds if any(iou(b, g) >= 0.5 for g in boda)), default=0.0)
            agree05 += int(best >= op_conf); agree01 += int(best >= 0.1)
    r = lambda k, m: round(k / m * 100, 1) if m else None  # noqa: E731
    return {"frames": n, "ref_box_frames": ref, "agree_iou50_rate_05": r(agree05, ref), "agree_iou50_rate_01": r(agree01, ref),
            "any_box_rate_05": r(any05, n), "caveat": "overlay.mp4(박스가 그려진 표시용) · 정답=장면 대본 · 참고 집합"}


def verdict(val: float | None, tgt: float, higher_is_better: bool, ci: list[float] | None = None) -> str:
    if val is None:
        return "미측정"
    ok = val >= tgt if higher_is_better else val <= tgt
    base = "달성" if ok else "미달"
    if ci and ci[0] <= tgt <= ci[1]:
        base += "(구간 걸침)"
    return base


def goal_check(cand: dict[str, Any] | None) -> list[dict[str, Any]]:
    s = (cand or {}).get("s510") or {}
    return [
        {"set": "510 held-out", "metric": "ap50", "target": f"≥{GOALS_FK['ap50_min']}", "value": s.get("ap50"),
         "verdict": verdict(s.get("ap50"), GOALS_FK["ap50_min"], True)},
        {"set": "510 held-out", "metric": "neg_fp_rate@0.5", "target": f"≤{GOALS_FK['neg_fp_rate_max']}%/장", "value": s.get("neg_fp_rate"),
         "ci95": s.get("neg_fp_rate_ci95"), "verdict": verdict(s.get("neg_fp_rate"), GOALS_FK["neg_fp_rate_max"], False, s.get("neg_fp_rate_ci95"))},
    ]


def _ci(v) -> str:
    return "-" if not v else f"[{v[0]}, {v[1]}]"


def _v(x) -> str:
    return "미측정" if x is None else f"{x}"


def _row(label: str, r: dict[str, Any] | None) -> str:
    if not r:
        return f"| {label} | 미측정 | | | | | | |"
    s = r.get("s510") or {}; f = r.get("field") or {}
    return (f"| {label} | {_v(s.get('ap50'))} | {_v(s.get('recall'))} {_ci(s.get('recall_ci95'))} | {_v(s.get('precision'))} | "
            f"{_v(s.get('neg_fp_rate'))} {_ci(s.get('neg_fp_rate_ci95'))} | {_v(f.get('agree_iou50_rate_05'))} / {_v(f.get('agree_iou50_rate_01'))} | "
            f"{_v(f.get('any_box_rate_05'))} | {r.get('weights', '')} |")


def render(baseline: dict[str, Any] | None, cand: dict[str, Any] | None, cand_label: str) -> str:
    lines = ["| 행 | 510 held-out AP50 | R@0.5 [W95] | P@0.5 | 음성 오탐률@0.5 [W95] (목표 ≤1%) | 학원 956 IoU≥0.5 일치 @0.5 / @0.1 | 학원 ≥1박스@0.5 | 가중치 |",
             "|---|---|---|---|---|---|---|---|",
             _row("전(v1)", baseline), _row(f"후({cand_label})", cand),
             f"| 참고 boda_ax YOLO(AGPL·후보 아님) | — | — | — | — | 대본 대비 {BODA_REF['field_script_rate']}%({BODA_REF['field_script_frac']}) | "
             f"{BODA_REF['field_present_rate']}%(present) | forklift_boda_ax.pt |"]
    if not baseline:
        lines.append(f"\n> 전(v1) 행 미측정 — `--write-baseline` 으로 같은 집합에서 재라. [참고] {V1_SMOKE_NOTE}")
    lines.append("\n**목표 판정(510 held-out 만)**\n")
    lines.append("| 지표 | 목표 | 값 | 판정 |\n|---|---|---|---|")
    for g in goal_check(cand):
        lines.append(f"| {g['metric']} | {g['target']} | {_v(g['value'])} {_ci(g.get('ci95'))} | {g['verdict']} |")
    lines.append(f"\n{GOALS_FK['note']}. 학원 집합은 참고(정답 대본·원본 미보존).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------
# 실측 경로(모델·파일)
# ---------------------------------------------------------------------------------------------------------------------
def load_items_510(labels: Path, images: Path, split: Path, classes: list[str], limit: int = 0) -> list[tuple[Path, list[list[float]]]]:
    """val 분할 stem 중 이미지가 있는 것만. GT = labels/<stem>.txt 의 forklift 줄(px xyxy)."""
    from PIL import Image
    fk = classes.index("forklift")
    idx = {p.stem: p for p in images.rglob("*") if p.suffix.lower() in IMG_EXTS}
    sp = json.loads(split.read_text(encoding="utf-8"))
    out = []
    for stem in sp["val"]:
        if stem not in idx:
            continue
        with Image.open(idx[stem]) as im:
            W, H = im.size
        gts = []
        lb = labels / f"{stem}.txt"
        if lb.exists():
            for ln in lb.read_text(encoding="utf-8").splitlines():
                t = ln.split()
                if len(t) >= 5 and int(t[0]) == fk:
                    cx, cy, w, h = map(float, t[1:5])
                    gts.append([(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H])
        out.append((idx[stem], gts))
        if limit and len(out) >= limit:
            break
    return out


def load_field_frames(root: Path, limit_per_scene: int = 0):
    """장면 폴더(dets.jsonl + overlay.mp4) → [(PIL 이미지, [boda 지게차 박스 px])]. forklift_field_rerun.py 와 같은 추림."""
    import cv2
    from PIL import Image
    frames = []
    for sc in sorted(os.listdir(root)):
        d = root / sc
        if not (d / "dets.jsonl").exists() or not (d / "overlay.mp4").exists():
            continue
        rows = [json.loads(ln) for ln in (d / "dets.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        cap = cv2.VideoCapture(str(d / "overlay.mp4")); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        k = len(rows); idx = [int(i * n / k) for i in range(k)] if n and k else []
        if limit_per_scene:
            idx = idx[:limit_per_scene]
        for j, fi in enumerate(idx):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, fr = cap.read()
            if not ok:
                continue
            H, W = fr.shape[:2]
            boda = [[b[0] * W, b[1] * H, b[2] * W, b[3] * H] for b in
                    (dd["bbox"] for dd in rows[j].get("detections", []) if dd.get("class") == "forklift" and not dd.get("stale"))]
            frames.append((Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), boda))
        cap.release()
    return frames


def load_model(weights: str, res: int):
    from rfdetr import RFDETRNano
    try:
        m = RFDETRNano(pretrain_weights=weights, resolution=res)
    except Exception:  # noqa: BLE001 — PTL 체크포인트(재학습 산출물)는 from_checkpoint 로
        from rfdetr import RFDETR
        m = RFDETR.from_checkpoint(weights, resolution=res)
    from aihub_smoke_eval import class_names_of
    cn = class_names_of(m)
    ids = {k for k, v in cn.items() if str(v) == "forklift"}
    if not ids:
        raise SystemExit(f"★가중치에 forklift 클래스가 없다: {cn}")
    return m, ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True); ap.add_argument("--label", default="")
    ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--s510-labels", default="D:/vigent_private_data/aihub/vigent_510/labels")
    ap.add_argument("--s510-images", default="D:/vigent_private_data/aihub/_inspect/510_src")
    ap.add_argument("--s510-split", default="D:/vigent_private_data/aihub/vigent_510/split.json")
    ap.add_argument("--field-root", default=FIELD_ROOT_DEFAULT); ap.add_argument("--skip-field", action="store_true")
    ap.add_argument("--baseline-json", default=str(BASELINE_JSON)); ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--out", default=""); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    label = a.label or Path(a.weights).stem
    from PIL import Image
    model, ids = load_model(a.weights, a.res)

    def predict_pil(im) -> list[tuple[list[float], float]]:
        det = model.predict(im, threshold=0.001)
        return [([float(v) for v in box], float(c)) for box, cid, c in zip(det.xyxy, det.class_id, det.confidence) if int(cid) in ids]

    result: dict[str, Any] = {"date": time.strftime("%Y-%m-%d %H:%M"), "weights": a.weights, "label": label, "res": a.res, "goals": GOALS_FK}
    labels, images, split = Path(a.s510_labels), Path(a.s510_images), Path(a.s510_split)
    if split.exists() and labels.exists():
        classes = (labels.parent / "classes.txt").read_text(encoding="utf-8").split()
        items = load_items_510(labels, images, split, classes, a.limit)
        print(f"[510 held-out] val 이미지 {len(items)}장 (분할 {split})")
        if items:
            t0 = time.time()
            result["s510"] = eval_510(items, lambda p: predict_pil(Image.open(p).convert("RGB")), GOALS_FK["op_conf"])
            result["s510"]["elapsed_s"] = round(time.time() - t0, 1)
            print(json.dumps(result["s510"], ensure_ascii=False))
        else:
            print("★510 val 에 이미지가 있는 stem 이 0장 — 원천 이미지(VS_07 등) 압축 해제·경로 확인")
    else:
        print(f"★510 변환본 없음({labels} / {split}) — `scripts/data/aihub_to_vigent.py --dataset 510` 먼저")
    if not a.skip_field and Path(a.field_root).exists():
        frames = load_field_frames(Path(a.field_root), a.limit)
        print(f"[학원 8/27 참고] 프레임 {len(frames)}")
        if frames:
            result["field"] = eval_field_frames(frames, predict_pil, GOALS_FK["op_conf"])
            print(json.dumps(result["field"], ensure_ascii=False))
    result["goal_check"] = goal_check(result)
    baseline = json.loads(Path(a.baseline_json).read_text(encoding="utf-8")) if Path(a.baseline_json).exists() else None
    if a.write_baseline:
        Path(a.baseline_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.baseline_json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[baseline] 전(v1) 행 저장 → {a.baseline_json}")
        baseline = result
    out = Path(a.out) if a.out else _ROOT / "audit" / f"forklift_harness_{label}_{time.strftime('%Y%m%d_%H%M')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + render(baseline if not a.write_baseline else baseline, None if a.write_baseline else result, label))
    print(f"\n원자료 → {out} ({out.stat().st_size} B)")
    return 0 if ("s510" in result or "field" in result) else 1


if __name__ == "__main__":
    sys.exit(main())
