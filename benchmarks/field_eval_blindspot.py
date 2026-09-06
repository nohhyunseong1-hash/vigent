#!/usr/bin/env python3
"""[R] 순환 없는 지표 — 모델의 진짜 사각지대를 센다.

## 왜 필요한가
현장 평가셋 정답지는 **이 모델의 출력에서 출발**했다(conf=0.10 초안 → 사람 검수). 그래서 사람이
손대지 않고 유지한 박스는 모델의 이번 예측과 좌표가 거의 그대로 같고(guard `_track_iou` 는
격리 프레임에서 좌표를 변형하지 않는다 — 실측 확인), 그 결과 mAP@50:95 가 부풀려진다
(field_eval_ppe 는 6개 클래스 전부 mAP@50 == mAP@50:95 로 나왔다).

그래서 정답지를 두 갈래로 나눠 따로 센다:
  A. **모델 유래(사람이 유지)** — 순환이라 성능 근거로 쓰면 안 되는 구간
  B. **사람이 새로 그린 것** — 모델이 원래 못 봤던 자리. ★이 구간의 재현율이 진짜 사각지대 지표★

## 갈래를 나누는 방법과 그 검증
초안 파일이 남아 있는 89장 구간은 **초안과 직접 대조**해 나눈다(정확).
파일럿 20장은 초안 원본(83건)이 보존돼 있지 않아, "예측과 IoU≥0.999 로 일치하면 모델 유래"라는
휴리스틱으로 나눈다. 이 휴리스틱이 믿을 만한지는 **89장 구간에서 두 방법의 결과를 비교해 검증**한다
(초안 대조 결과와 휴리스틱 결과가 어긋나면 경고를 띄운다 — 규칙7).

사용법:
  python benchmarks/run_eval.py --mode pipeline --dataset field_eval_person \\
      --dump-preds benchmarks/results/preds_field_eval_person.json
  python benchmarks/run_eval.py --mode pipeline --dataset field_eval_ppe \\
      --dump-preds benchmarks/results/preds_field_eval_ppe.json
  python benchmarks/field_eval_blindspot.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import field_eval  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)
_FE = field_eval()
_RES = _ROOT / "benchmarks" / "results"
_DRAFT89 = _FE / "rest89" / "labels_backup_20260808_002915"   # push89 로 올린 초안 320건(정확한 사본)
_PILOT_LABELS = _FE / "pilot20" / "labels"

IOU_MATCH = 0.50      # 검출 성공 판정 기준(COCO 표준)
IOU_SAME = 0.999      # '같은 박스'로 볼 기준(모델 유래 판정용)


def _iou(a: list[float], b: list[float]) -> float:
    """a,b = [x, y, w, h] (픽셀)."""
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    iy = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _load_draft89(classes: list[str]) -> dict[str, list[tuple[int, float, float, float, float]]]:
    out: dict[str, list[tuple[int, float, float, float, float]]] = {}
    if not _DRAFT89.exists():
        return out
    for p in _DRAFT89.glob("*.txt"):
        if p.name == "classes.txt":
            continue
        boxes = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            a = ln.split()
            boxes.append((int(a[0]), *(float(x) for x in a[1:5])))
        out[p.stem] = boxes
    return out


def analyse(path: Path) -> None:
    d = json.loads(path.read_text(encoding="utf-8"))
    gt_names: list[str] = d["gt_names"]
    imgs = {im["id"]: im for im in d["images"]}
    stem_of = {im["id"]: Path(im["file_name"]).stem for im in d["images"]}
    pilot_stems = {p.stem for p in _PILOT_LABELS.glob("*.txt") if p.name != "classes.txt"}

    gt_by_img: dict[int, list[dict]] = defaultdict(list)
    for a in d["gt_annotations"]:
        gt_by_img[a["image_id"]].append(a)
    dt_by_img: dict[int, list[dict]] = defaultdict(list)
    for a in d["detections"]:
        dt_by_img[a["image_id"]].append(a)

    draft89 = _load_draft89(gt_names)
    # 전체 7클래스 스킴 기준 id → 이 데이터셋의 클래스 이름
    all_names = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest", "Mask", "NO-Mask"]

    tp = fp = fn = 0
    grp_tot: Counter[str] = Counter()
    grp_hit: Counter[str] = Counter()
    per_class_tot: Counter[str] = Counter()
    per_class_hit: Counter[str] = Counter()
    heur_vs_draft = {"agree": 0, "disagree": 0}
    blind_examples: list[str] = []

    for img_id, im in imgs.items():
        gts = gt_by_img.get(img_id, [])
        dts = sorted(dt_by_img.get(img_id, []), key=lambda x: -x["score"])
        stem = stem_of[img_id]

        # 초안(89장 구간)의 해당 프레임 박스 → 픽셀 좌표로
        W, H = im["width"], im["height"]
        draft_px: list[tuple[str, list[float]]] = []
        for cid, cx, cy, bw, bh in draft89.get(stem, []):
            nm = all_names[cid]
            if nm not in gt_names:
                continue
            draft_px.append((nm, [(cx - bw / 2) * W, (cy - bh / 2) * H, bw * W, bh * H]))

        used: set[int] = set()
        for g in gts:
            gname = gt_names[g["category_id"] - 1]
            per_class_tot[gname] += 1

            # ── 검출 성공 여부(IoU≥0.5, 같은 클래스, 1:1) ──
            best_i, best_iou = -1, IOU_MATCH
            for i, dt in enumerate(dts):
                if i in used or gt_names[dt["category_id"] - 1] != gname:
                    continue
                v = _iou(g["bbox"], dt["bbox"])
                if v >= best_iou:
                    best_i, best_iou = i, v
            hit = best_i >= 0
            if hit:
                used.add(best_i)
                tp += 1
                per_class_hit[gname] += 1
            else:
                fn += 1

            # ── 이 GT 박스가 '모델 유래'인가 '사람이 새로 그린 것'인가 ──
            heur = any(gt_names[dt["category_id"] - 1] == gname and _iou(g["bbox"], dt["bbox"]) >= IOU_SAME
                       for dt in dts)
            if stem in pilot_stems or not draft_px:
                origin = "모델 유래" if heur else "사람 추가"
            else:
                by_draft = any(nm == gname and _iou(g["bbox"], bb) >= IOU_SAME for nm, bb in draft_px)
                origin = "모델 유래" if by_draft else "사람 추가"
                heur_vs_draft["agree" if heur == by_draft else "disagree"] += 1

            grp_tot[origin] += 1
            if hit:
                grp_hit[origin] += 1
            elif origin == "사람 추가" and len(blind_examples) < 8:
                blind_examples.append(f"{stem.replace('KakaoTalk_20260807_', '')} / {gname}")

        fp += len(dts) - len(used)

    n_gt, n_dt = len(d["gt_annotations"]), len(d["detections"])
    prec = tp / n_dt * 100 if n_dt else 0.0
    rec = tp / n_gt * 100 if n_gt else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    print(f"\n{'=' * 66}\n{d['dataset']} / {d['mode']}  (IoU≥{IOU_MATCH} 매칭)\n{'=' * 66}")
    print(f"  정답 {n_gt}건 · 예측 {n_dt}건")
    print(f"  맞음(TP) {tp} · 헛봄(FP) {fp} · 놓침(FN) {fn}")
    print(f"  정밀도 {prec:.1f}%  ·  재현율 {rec:.1f}%  ·  F1 {f1:.1f}%")

    print("\n  ── 정답 출처별 재현율 ──")
    for k in ("모델 유래", "사람 추가"):
        t, h = grp_tot.get(k, 0), grp_hit.get(k, 0)
        r = h / t * 100 if t else 0.0
        note = " ← ★진짜 사각지대 지표" if k == "사람 추가" else " (순환 — 성능 근거로 쓰지 말 것)"
        print(f"    {k:<8} {h:>4}/{t:<4} = {r:5.1f}%{note}")

    print("\n  ── 클래스별 재현율 ──")
    for c in gt_names:
        t, h = per_class_tot.get(c, 0), per_class_hit.get(c, 0)
        r = h / t * 100 if t else 0.0
        warn = "  ※표본 부족" if t < 10 else ""
        print(f"    {c:<16} {h:>4}/{t:<4} = {r:5.1f}%{warn}")

    if heur_vs_draft["agree"] + heur_vs_draft["disagree"]:
        tot = heur_vs_draft["agree"] + heur_vs_draft["disagree"]
        ok = heur_vs_draft["agree"] / tot * 100
        print("\n  ── 출처 판정 휴리스틱 검증(89장 구간, 초안 대조와 비교) ──")
        print(f"    일치 {heur_vs_draft['agree']}/{tot} = {ok:.1f}%"
              + ("" if ok >= 99 else "  ★불일치 있음 — 파일럿 20장 구간 판정은 참고치로만 볼 것"))

    if blind_examples:
        print(f"\n  놓친 '사람 추가' 예시: {blind_examples}")


def main() -> None:
    found = False
    for name in ("preds_field_eval_person.json", "preds_field_eval_ppe.json"):
        p = _RES / name
        if p.exists():
            analyse(p)
            found = True
        else:
            print(f"[없음] {p} — run_eval.py 를 --dump-preds 로 먼저 실행하세요.")
    if not found:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
