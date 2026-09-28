#!/usr/bin/env python3
"""eval_v1_heldout.py — v1(ppe_rfdetr_v1.pth)의 **정직한 "전" 점수**. [T-0c, 2026-09-25]

★왜 있는가
  기존 "test 82 box mAP@50 75.62%" 는 valid/test 영상의 83~93% 가 train 에도 들어간 **누출 분할**에서 잰 값이다
  (docs/model/ppe_rfdetr_v1_provenance.md §3-1). 재학습 전후 비교표의 "전" 행은 **v1 이 한 번도 보지 않은 이미지**로 다시 재야 한다.

무엇을 하는가 (학습은 하지 않는다 — 기존 가중치를 새 분할로 평가만)
  1. held-out 구성: CSS v27 의 valid+test 이미지 중 (`--split-rule video`, 기본)
       · 원본 stem 이 train 에 없고
       · 유래 영상 id 가 train 에 없는 것 — 영상 id 는 **확장자를 뗀** 이름(`IMG_0871_mp4` 와 `IMG_0871_MOV` 는 같은 영상;
         mp4/mov/m4v/avi/mkv/webm, 대소문자 무시). ★2026-09-25 재검토에서 `_mp4` 만 보던 1차 규칙이 `_mov`·`_MP4` 프레임 10장을 놓쳤다.
       · `youtube-N` 묶음 전부 제외 — 번호가 인접(≤3)한 쌍 중 화소가 거의 동일한 쌍(NCC 0.997)이 있어 **연속 프레임**이고,
         held-out 후보 55장 중 39장이 train 에 번호차 ≤3 인 장을 둔다(파일명으로 영상을 나눌 수 없어 묶음째 제외).
       · 원본당 1장(증강본 제외 — valid/test 는 원래 1장이나 2장짜리 2개는 첫 장만)
     나머지 묶음(construction-N-·숫자만·ppe_N·VOC 2008/2009·airport_inside 등)은 인접 번호 쌍 검사에서 연속 프레임 증거가
     없어 남긴다 — 단 "같은 현장·같은 사람" 수준의 중복은 파일명·화소 검사로 못 본다(미검증 잔존 위험).
     640×640 export 그대로 쓴다(v1 이 그 조건으로 학습됐다). 분할 파일 목록을 JSON 으로 남겨 재학습 비교에서 같은 집합을 쓴다.
     `--split-rule stem` 은 1차(2026-09-25 19:50) 규칙 재현용 — `_mp4` 소문자만 영상으로 보고 youtube 를 남긴 156장. 영상 누출이
     남아 있으므로 **기준선으로 쓰지 않는다**(`benchmarks/results/v1_heldout_stem_only_156.json`).
  2. 추론: rfdetr predict, 해상도 384(배포 조건), 임계 0.05 로 전부 받아 AP 계산, P/R 은 앱 임계(tuning.yaml detect.conf.ppe, 현재 0.35).
  3. 지표: 클래스별 GT·TP·FP·FN·정밀도·재현율(IoU≥0.5, 클래스 일치, 1:1 매칭) + Wilson 95% 구간 + AP@50(전점 보간).
     10클래스 전부 + 우리 4클래스 평균. ★Wilson 구간은 박스를 독립 시행으로 본 근사다 — 한 장 안의 박스들은 완전히 독립이 아니다.

★비교 하네스 (2026-09-25 마무리 2)
  `--weights <임의 가중치>` 로 돌리면 같은 91장에서 평가하고 **"전(v1)" 행**(`benchmarks/results/v1_heldout_eval.json` = provenance §7-2)
  을 항상 나란히 찍는다. 세 평가 집합(held-out 91 / 사고영상 dev 74 / 재방문 현장 정답지)을 한 표로 — dev 74 는 `--dev74`(앱
  파이프라인, x4b_score_candidates.score_one) 또는 `--dev74-json`, 현장 정답지는 `--field-gt-json` 이 없으면 **"미확보"** 로 적는다.
  재학습 목표(provenance §8)는 `GOALS` 상수에 있고 판정(달성/미달/미측정)을 같이 찍는다. 기준선 파일은 `--write-baseline` 없이는
  덮어쓰지 않는다. 테스트: `tests/test_ppe_compare_harness.py`(v1 로 돌리면 §7-2 재현).

사용:
    python scripts/eval/eval_v1_heldout.py                                   # v1 자기 재현(전 == 후 여야 한다)
    python scripts/eval/eval_v1_heldout.py --weights runs/.../best.pth --label aihub_v2 [--dev74]
    python scripts/eval/eval_v1_heldout.py --split-rule stem                 # 1차 156장 재현(기준선 아님)
"""
from __future__ import annotations

import argparse
import json
import os
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
_VID_STEM = re.compile(r"^(.*_mp4)-\d+$")                                                     # 1차 규칙(재현용)
_VID = re.compile(r"^(.*?)[_-](?:mp4|mov|m4v|avi|mkv|webm)-\d+$", re.IGNORECASE)              # 확장자 뗀 영상 id
# 파일명으로 영상을 나눌 수 없지만 연속 프레임 증거가 있는 묶음(이유는 상단 docstring)
_FAMILY_EXCLUDE = {"youtube-N": re.compile(r"^youtube-\d+$", re.IGNORECASE)}


def stem_of(p: Path) -> str:
    m = _RF.match(p.stem)
    return m.group(1) if m else p.stem


def video_of(stem: str, rule: str = "video") -> str | None:
    if rule == "stem":
        m = _VID_STEM.match(stem)
        return m.group(1) if m else None
    m = _VID.match(stem)
    return m.group(1).lower() if m else None


def family_excluded(stem: str) -> str | None:
    for name, rx in _FAMILY_EXCLUDE.items():
        if rx.match(stem):
            return name
    return None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson 95% 구간(%). n=0 이면 None."""
    if n == 0:
        return None
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return round(max(0.0, c - h) * 100, 1), round(min(1.0, c + h) * 100, 1)


def build_heldout(rule: str = "video") -> tuple[list[Path], dict]:
    """미노출 집합 + 그 근거 수치. rule='video'(기본, 엄격) 또는 'stem'(1차 규칙 재현 — 영상 누출 잔존)."""
    train_stems: set[str] = set(); train_vids: set[str] = set()
    for p in (DS / "train" / "images").glob("*"):
        s = stem_of(p); train_stems.add(s)
        v = video_of(s, rule)
        if v:
            train_vids.add(v)
    keep: list[Path] = []; seen: set[str] = set(); dropped = defaultdict(int)
    for split in ("valid", "test"):
        for p in sorted((DS / split / "images").glob("*")):
            s = stem_of(p); v = video_of(s, rule)
            if s in train_stems:
                dropped["원본 stem 이 train 에 있음"] += 1; continue
            if v and v in train_vids:
                dropped["유래 영상이 train 에 있음"] += 1; continue
            fam = family_excluded(s) if rule == "video" else None
            if fam:
                dropped[f"연속 프레임 묶음({fam}) 제외"] += 1; continue
            if s in seen:
                dropped["같은 원본의 두 번째 증강본"] += 1; continue
            seen.add(s); keep.append(p)
    n_orig_all = len(train_stems | {stem_of(p) for sp in ("valid", "test") for p in (DS / sp / "images").glob("*")})
    vids_in_keep = {video_of(stem_of(p), rule) for p in keep} - {None}
    info = {"split_rule": rule, "heldout_images": len(keep), "heldout_unique_originals": len(seen), "all_unique_originals": n_orig_all,
            "heldout_share_of_originals": round(len(seen) / max(1, n_orig_all), 3),
            "valid_test_total": sum(1 for sp in ("valid", "test") for _ in (DS / sp / "images").glob("*")),
            "dropped": dict(dropped), "train_videos": len(train_vids),
            "heldout_videos": sorted(vids_in_keep), "heldout_videos_in_train": sorted(vids_in_keep & train_vids)}
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


import labels as _labels  # noqa: E402

_TO_CSS = dict(_labels.STD_TO_CSS)                                        # [B-5] 정본(labels.CSS_TO_STD 의 역방향)


def to_css_name(name: str) -> str:
    """우리 표준 클래스명(변환기·재학습 산출물) → CSS 정답지(data.yaml) 이름. CSS 이름은 그대로."""
    return _TO_CSS.get(str(name), str(name))


CUBLAS_ENV = "CUBLAS_WORKSPACE_CONFIG"
CUBLAS_WORKSPACE = ":4096:8"


def enable_determinism(warn_only: bool = True) -> dict:
    """[CODE_AUDIT_20260928 B-2] 평가 경로의 GPU 비결정성을 끈다 — 같은 가중치·같은 집합이면 같은 숫자가 나와야 기준선 재현 테스트가 뜻이 있다.
    실측 이력: 단독 실행은 매번 같았지만 전체 스위트 안에서는 NO-Mask fp 35↔36(09-25) · Person fp 48↔46(09-27) · Safety Vest AP50 82.8↔83.2
    (09-28 3회) · machinery 90.3↔91.4(09-28) 로 흔들렸다. 원인은 cuDNN 자동 알고리즘 선택(benchmark)이 GPU 메모리 상태에 따라 다른 커널을
    고르는 것 + cuBLAS 작업공간 비결정. 여기서 cudnn.benchmark=False·deterministic=True·use_deterministic_algorithms(True) 를 켠다.
    ★CUBLAS_WORKSPACE_CONFIG 는 cuBLAS 핸들이 만들어지기 **전에** 있어야 효과가 있다(같은 프로세스에서 CUDA 를 이미 썼다면 늦을 수 있다) —
      그래서 env 는 setdefault 로만 두고, 결정성의 주력은 cudnn 플래그다. warn_only=True: 결정적 구현이 없는 연산은 경고만 하고 계속 돈다.
    반환: 적용 상태 dict(테스트·리포트용)."""
    os.environ.setdefault(CUBLAS_ENV, CUBLAS_WORKSPACE)
    import torch
    st = {"cublas_workspace_config": os.environ.get(CUBLAS_ENV, ""), "cudnn_benchmark": None, "cudnn_deterministic": None,
          "deterministic_algorithms": None, "warn_only": warn_only, "note": ""}
    try:
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True, warn_only=warn_only)
        st.update(cudnn_benchmark=bool(torch.backends.cudnn.benchmark), cudnn_deterministic=bool(torch.backends.cudnn.deterministic),
                  deterministic_algorithms=bool(torch.are_deterministic_algorithms_enabled()))
    except Exception as ex:  # noqa: BLE001  구버전 torch·테스트의 가짜 torch 등 — 평가는 계속하되 상태에 남긴다
        st["note"] = f"결정성 설정 실패: {type(ex).__name__}: {ex}"
        print(f"★[B-2] {st['note']}", file=sys.stderr, flush=True)
    return st


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

# ---------------------------------------------------------------------------------------------------------------------
# 비교 하네스 (2026-09-25 T-0c 마무리 2): 임의 가중치를 같은 91장으로 평가하고 "전(v1)" 행과 나란히 놓는다
# ---------------------------------------------------------------------------------------------------------------------
BASELINE_JSON = _ROOT / "benchmarks" / "results" / "v1_heldout_eval.json"       # "전(v1)" 행 = provenance.md §7-2
V1_DEV74 = {  # 사고영상 dev 74장 v1 현장 기준선(2026-08-10) — 앱 파이프라인(1fps·ByteTrack) 경유. 클래스별 표는 미기록
    "source": "benchmarks/v1_field_baseline_report.md:91-94 (측정 2026-08-10)",
    "ppe_precision": 93.6, "ppe_tp": 160, "ppe_fp": 11, "ppe_recall": 64.8, "ppe_gt": 247,
    "nh_interval": [25.9, 100.0], "nh_n": 14,
}
GOALS = {  # 재학습 목표 선언(2026-09-25, provenance.md §8 · P3_BACKLOG B-finetune)
    "primary": {  # held-out 91장 @0.35 — 정밀도는 v1 수준 이상 유지
        "NO-Hardhat": {"recall_min": 85.0, "precision_min": 69.5},
        "NO-Safety Vest": {"recall_min": 90.0, "precision_min": 86.9},
    },
    "secondary": {"dev74_ppe_recall_min": 80.0},   # 사고영상 dev 74장 PPE 전체 재현율 64.8 → 80 이상
    "field": {"NO-Hardhat": {"recall_min": 85.0}, "NO-Safety Vest": {"recall_min": 90.0}, "neg_fp_rate_max": 1.0},   # [2026-09-27] 현장 held-out 300 합격선(최종)
    "final": "재방문 현장 정답지에서만 판정 — 위 둘은 '가망 확인'",
}


def op_conf_default() -> float:
    import yaml
    tun = yaml.safe_load((_ROOT / "config" / "tuning.yaml").read_text(encoding="utf-8"))
    return float(((tun.get("detect") or {}).get("conf") or {}).get("ppe", 0.35))


def make_predictor(weights: str, res: int, names: list[str]):
    """rfdetr 체크포인트 → (predict(PIL)->[(CSS 클래스명, box, conf)], device). class_id 는 0-indexed 로 class_names 에 대응.
    ★재학습 산출물은 우리 표준 이름(person·Safety-Vest·NO-Safety-Vest)을 내므로 CSS 정답지 이름으로 맞춘다(2026-09-26)"""
    import torch
    from rfdetr import RFDETRNano
    enable_determinism()                                   # [B-2] 모델을 만들기 전에(cudnn 플래그는 첫 conv 전이면 된다)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = RFDETRNano(pretrain_weights=weights, device=dev, resolution=res)
    # [B-2] optimize_for_inference(export + jit.trace, fp32) 는 **숫자가 달라지는 경로 선택**이다 — 실패를 삼키면 eager 로 조용히 떨어져
    #   같은 가중치·같은 집합에서 AP50 이 0.4 만큼 다른 두 상태(82.8/83.2)가 생긴다(의심 원인, 아래 probe 로 확인). 실패하면 GPU 캐시를 비우고
    #   한 번 더 시도하고, 그래도 안 되면 stderr 에 남기고 predict.optimized=False 로 표시한다(하네스 테스트가 이 값을 본다).
    optimized, err = False, ""
    for attempt in (1, 2):
        try:
            m.optimize_for_inference()
            optimized = True
            break
        except Exception as ex:  # noqa: BLE001
            err = f"{type(ex).__name__}: {str(ex)[:200]}"
            print(f"★[B-2] optimize_for_inference 실패({attempt}/2): {err}", file=sys.stderr, flush=True)
            try:
                import gc
                gc.collect(); torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass
    cls_names = [to_css_name(c) for c in (getattr(m, "class_names", None) or names)]
    # ★[CODE_AUDIT_20260928 #9] 평가기도 슬롯 가드 — 우리 4클래스가 없는 가중치는 채점하지 않는다(엉뚱한 가중치가 조용히 채점되는 것 방지)
    missing = [c for c in OUR4 if c not in cls_names]
    if getattr(m, "class_names", None) and missing:
        raise SystemExit(f"★가중치 class_names 에 우리 클래스가 없다: 없음 {missing} · class_names={list(getattr(m, 'class_names'))} ({weights})")

    def predict(im):
        det = m.predict(im, threshold=0.05)
        preds = []
        for box, cid, conf in zip(det.xyxy, det.class_id, det.confidence):
            cid = int(cid)
            if 0 <= cid < len(cls_names):
                preds.append((cls_names[cid], [float(x) for x in box], float(conf)))
        return preds
    predict.optimized = optimized          # type: ignore[attr-defined]
    predict.optimize_error = err           # type: ignore[attr-defined]
    return predict, dev


def score_items(predict, items: list[tuple[Path, list[tuple[str, list[float]]]]], names: list[str], op_conf: float, iou_thr: float = 0.5,
                say=print) -> dict:
    """공통 채점기: items=[(이미지, GT)] 를 predict 로 채점 → 클래스별 gt/tp/fp/fn·P/R(Wilson)·AP50 rows + summary. [2026-09-27 field 확장으로 분리]"""
    from PIL import Image
    n_gt: dict[str, int] = defaultdict(int); scored: dict[str, list] = defaultdict(list)
    op: dict[str, dict[str, int]] = {n: {"TP": 0, "FP": 0, "FN": 0} for n in names}
    t0 = time.time()
    for i, (p, gts) in enumerate(items, 1):
        for g, _ in gts:
            n_gt[g] += 1
        preds = predict(Image.open(p).convert("RGB"))
        for name, conf, tp in match(preds, gts, iou_thr):
            scored[name].append((conf, tp))
        op_preds = [pr for pr in preds if pr[2] >= op_conf]           # 운용점 P/R: 임계 이상만으로 다시 매칭
        matched = match(op_preds, gts, iou_thr)
        for name, _, tp in matched:
            if name in op:
                op[name]["TP" if tp else "FP"] += 1
        for gname in {g for g, _ in gts}:
            gt_c = sum(1 for g, _ in gts if g == gname)
            tp_c = sum(1 for n, _, tp in matched if tp and n == gname)
            op.setdefault(gname, {"TP": 0, "FP": 0, "FN": 0})["FN"] += gt_c - tp_c
        if i % 20 == 0:
            say(f"  {i}/{len(items)} ({time.time() - t0:.0f}s)")
    rows = []
    for n in names:
        tp, fp, fn = op[n]["TP"], op[n]["FP"], op[n]["FN"]
        prec = tp / (tp + fp) if tp + fp else float("nan"); rec = tp / (tp + fn) if tp + fn else float("nan")
        rows.append({"class": n, "gt": n_gt[n], "tp": tp, "fp": fp, "fn": fn,
                     "precision": None if np.isnan(prec) else round(prec * 100, 1), "precision_ci95": wilson(tp, tp + fp),
                     "recall": None if np.isnan(rec) else round(rec * 100, 1), "recall_ci95": wilson(tp, tp + fn),
                     "ap50": None if n_gt[n] == 0 else round(ap50(scored[n], n_gt[n]) * 100, 1)})

    def _mean(key, subset):
        v = [r[key] for r in rows if r["class"] in subset and r[key] is not None]
        return round(sum(v) / len(v), 1) if v else None
    summary = {"mAP50_all10": _mean("ap50", names), "mAP50_our4": _mean("ap50", OUR4),
               "recall_our4_mean": _mean("recall", OUR4), "precision_our4_mean": _mean("precision", OUR4),
               "optimized": getattr(predict, "optimized", None),                 # [B-2] jit 경로 여부(None = 외부 predictor)
               "optimize_error": getattr(predict, "optimize_error", "")}
    return {"rows": rows, "summary": summary, "elapsed_s": round(time.time() - t0, 1), "images": len(items)}


def evaluate(weights: str, res: int = 384, iou_thr: float = 0.5, split_rule: str = "video", limit: int = 0,
             verbose: bool = True) -> dict:
    """held-out 에서 가중치 하나를 평가한다(학습 없음). 반환 dict 는 JSON 으로 그대로 저장 가능."""
    import yaml
    names = yaml.safe_load((DS / "data.yaml").read_text(encoding="utf-8"))["names"]
    op_conf = op_conf_default()

    imgs, info = build_heldout(split_rule)
    if limit:
        imgs = imgs[:limit]
    say = print if verbose else (lambda *a, **k: None)
    say(f"held-out[{split_rule}]: {info['heldout_images']}장 / 고유 원본 {info['heldout_unique_originals']} / 전체 원본 {info['all_unique_originals']} "
        f"= {info['heldout_share_of_originals']:.1%} · 제외 {info['dropped']}")
    say(f"  남은 영상 유래: {info['heldout_videos']} · 그중 train 에도 있는 영상: {info['heldout_videos_in_train']}")
    if info["heldout_videos_in_train"]:
        raise RuntimeError("held-out 에 train 과 같은 영상이 남아 있다: " + ", ".join(info["heldout_videos_in_train"]))
    if info["heldout_share_of_originals"] < 0.20:
        say("★주의: held-out 이 전체 원본의 20% 미만이다 — 이것이 v1 이 안 본 이미지의 전부다(더 늘리면 train 원본이 섞인다)")
    predict, dev = make_predictor(weights, res, names)
    r = score_items(predict, [(p, load_gt(p, names)) for p in imgs], names, op_conf, iou_thr, say)
    return {"date": time.strftime("%Y-%m-%d %H:%M"), "weights": str(weights), "resolution": res, "op_conf": op_conf, "iou": iou_thr,
            "device": dev, "heldout": info, "heldout_files": [str(p.relative_to(_ROOT)) for p in imgs],
            "rows": r["rows"], "summary": r["summary"], "elapsed_s": r["elapsed_s"]}


# ── 현장 held-out(세 번째 집합, 2026-09-27) — field_prelabel + field_split heldout 산출 폴더 ──────────────────────────────
def load_field_heldout(field_dir: Path) -> tuple[list[tuple[Path, list[tuple[str, list[float]]]]], list[Path], dict]:
    """heldout.json 의 frames(양성)·negatives(음성)를 이미지 경로+GT 로. 라벨은 YOLO(classes.txt 순, 검수 후 값) → CSS 이름."""
    d = Path(field_dir); h = json.loads((d / "heldout.json").read_text(encoding="utf-8"))
    names = (d / "classes.txt").read_text(encoding="utf-8").split()
    from PIL import Image
    items = []; missing = []
    for stem in h["frames"]:
        img = d / "images" / f"{stem}.jpg"; lb = d / "labels" / f"{stem}.txt"
        if not img.exists():
            missing.append(stem); continue
        with Image.open(img) as im:
            W, H = im.size
        gts = []
        for ln in (lb.read_text(encoding="utf-8").splitlines() if lb.exists() else []):
            t = ln.split()
            if len(t) < 5:
                continue
            c, cx, cy, w, hh = int(t[0]), *map(float, t[1:5])
            gts.append((to_css_name(names[c]), [(cx - w / 2) * W, (cy - hh / 2) * H, (cx + w / 2) * W, (cy + hh / 2) * H]))
        items.append((img, gts))
    negs = [d / "negatives" / f"{s}.jpg" for s in h.get("negatives", []) if (d / "negatives" / f"{s}.jpg").exists()]
    info = {"dir": str(d), "policy": h.get("policy"), "n_positive_listed": len(h["frames"]), "n_positive_found": len(items), "missing": missing[:5],
            "n_negative_listed": len(h.get("negatives", [])), "n_negative_found": len(negs), "strata": h.get("strata"), "classes": names,
            "labels_reviewed_note": "라벨은 CVAT 검수본이어야 한다(초벌 그대로면 v1 자기 채점) — labels_meta 의 prelabel 필드로 구분"}
    return items, negs, info


def negative_fp(predict, negs: list[Path], op_conf: float, say=print) -> dict:
    """음성 프레임(사람 없음)에서 운용 임계 이상 박스가 1개라도 나오면 오탐 프레임. → 프레임 오탐률(Wilson) + 클래스별 박스 수."""
    from PIL import Image
    fp_frames = 0; by_cls: dict[str, int] = defaultdict(int); t0 = time.time()
    for i, p in enumerate(negs, 1):
        preds = [pr for pr in predict(Image.open(p).convert("RGB")) if pr[2] >= op_conf]
        if preds:
            fp_frames += 1
            for n, _b, _c in preds:
                by_cls[n] += 1
        if i % 50 == 0:
            say(f"  neg {i}/{len(negs)} ({time.time() - t0:.0f}s)")
    rate = None if not negs else round(fp_frames / len(negs) * 100, 2)
    return {"neg_images": len(negs), "fp_images": fp_frames, "neg_fp_rate": rate, "neg_fp_rate_ci95": wilson(fp_frames, len(negs)) if negs else None,
            "fp_boxes_by_class": dict(by_cls)}


def evaluate_field(weights: str, field_dir: str, res: int = 384, iou_thr: float = 0.5, limit: int = 0, verbose: bool = True) -> dict:
    """현장 held-out 300(+음성)에서 한 가중치를 채점. rows 는 CSS 이름(NO-Hardhat·NO-Safety Vest·Person…)으로 맞춰 다른 표와 같은 형식."""
    say = print if verbose else (lambda *a, **k: None)
    items, negs, info = load_field_heldout(Path(field_dir))
    if limit:
        items = items[:limit]; negs = negs[:limit]
    if not items:
        raise SystemExit(f"★현장 held-out 양성 0장: {field_dir}")
    names = sorted({to_css_name(n) for n in info["classes"]}, key=lambda n: (n not in OUR4, n))
    op_conf = op_conf_default()
    say(f"field held-out: 양성 {len(items)}장(목록 {info['n_positive_listed']}) · 음성 {len(negs)}장 · 클래스 {names} · @{op_conf}")
    predict, dev = make_predictor(weights, res, names)
    r = score_items(predict, items, names, op_conf, iou_thr, say)
    neg = negative_fp(predict, negs, op_conf, say)
    return {"date": time.strftime("%Y-%m-%d %H:%M"), "weights": str(weights), "resolution": res, "op_conf": op_conf, "iou": iou_thr, "device": dev,
            "field": info, "rows": r["rows"], "summary": r["summary"], "negatives": neg, "elapsed_s": round(r["elapsed_s"], 1)}


def field_goal_check(field: dict | None) -> list[dict]:
    """합격선(GOALS.field): NO-Hardhat R ≥85 · NO-Safety Vest R ≥90 · 음성 오탐률 ≤1%. 판정은 verdict_of(구간 걸침 표시)."""
    if not field:
        return []
    out = []
    for cls, g in ((k, v) for k, v in GOALS["field"].items() if isinstance(v, dict)):
        r = _row(field, cls); val = None if r is None else r["recall"]
        out.append({"set": "field", "class": cls, "metric": "recall", "value": val, "target": g["recall_min"],
                    "verdict": verdict_of(val, g["recall_min"], None if r is None else r["recall_ci95"])})
    n = field.get("negatives") or {}; rate = n.get("neg_fp_rate"); mx = GOALS["field"]["neg_fp_rate_max"]
    v = "미측정" if rate is None else ("달성" if rate <= mx else "미달")
    out.append({"set": "field", "class": "(negatives)", "metric": "neg_fp_rate", "value": rate, "target": mx, "verdict": v, "ci95": n.get("neg_fp_rate_ci95")})
    return out


def _ci(v) -> str:
    return "-" if not v else f"[{v[0]}, {v[1]}]"


def _row(result: dict | None, cls: str) -> dict | None:
    if not result:
        return None
    return next((r for r in result["rows"] if r["class"] == cls), None)


def verdict_of(val: float | None, tgt: float, ci: tuple[float, float] | None = None) -> str:
    """점추정으로 달성/미달, Wilson 구간이 목표를 걸치면 '(구간 걸침)' 을 붙인다(§8 — 소표본 단서)."""
    if val is None:
        return "미측정"
    base = "달성" if val >= tgt else "미달"
    if ci and ci[0] < tgt <= ci[1]:
        return base + "(구간 걸침)"
    return base


def goal_check(cand: dict | None) -> list[dict]:
    """1차 목표(held-out 91장 @0.35) 판정. cand 가 없으면 전부 '미측정'."""
    out = []
    for cls, g in GOALS["primary"].items():
        r = _row(cand, cls)
        for key, tgt in (("recall", g["recall_min"]), ("precision", g["precision_min"])):
            val = None if r is None else r[key]
            ci = None if r is None else r[f"{key}_ci95"]
            out.append({"set": "held-out 91", "class": cls, "metric": key, "target_min": tgt, "value": val,
                        "ci95": ci, "verdict": verdict_of(val, tgt, ci)})
    return out


def render_heldout_compare(baseline: dict | None, cand: dict | None, cand_label: str) -> str:
    """클래스별 전(v1) ↔ 후 비교표(마크다운). 한쪽이 없으면 '미측정'."""
    classes = [r["class"] for r in (baseline or cand)["rows"]] if (baseline or cand) else []
    L = [f"| 클래스 | 전(v1) R% [W95] | {cand_label} R% [W95] | ΔR | 전 P% [W95] | {cand_label} P% [W95] | ΔP | 전 AP50 | {cand_label} AP50 | ΔAP |",
         "|---|---|---|---|---|---|---|---|---|---|"]

    def cell(r, key):
        if r is None or r[key] is None:
            return "미측정"
        ci = r.get(key + "_ci95")
        return f"{r[key]} {_ci(ci)}" if ci else f"{r[key]}"

    def delta(b, c, key):
        if b is None or c is None or b[key] is None or c[key] is None:
            return "-"
        d = round(c[key] - b[key], 1)
        return f"{d:+.1f}"
    for cls in classes:
        b, c = _row(baseline, cls), _row(cand, cls)
        mark = "**" if cls in OUR4 else ""
        L.append(f"| {mark}{cls}{mark} | {cell(b, 'recall')} | {cell(c, 'recall')} | {delta(b, c, 'recall')} | {cell(b, 'precision')} | "
                 f"{cell(c, 'precision')} | {delta(b, c, 'precision')} | {cell(b, 'ap50')} | {cell(c, 'ap50')} | {delta(b, c, 'ap50')} |")
    for label, key in (("우리 4클래스 AP50 평균", "mAP50_our4"), ("10클래스 mAP@50", "mAP50_all10")):
        bs = None if not baseline else baseline["summary"][key]; cs = None if not cand else cand["summary"][key]
        d = "-" if bs is None or cs is None else f"{cs - bs:+.1f}"
        L.append(f"| {label} | | | | | | | {bs if bs is not None else '미측정'} | {cs if cs is not None else '미측정'} | {d} |")
    return "\n".join(L)


def render_three_sets(baseline: dict | None, cand: dict | None, cand_label: str, dev74_cand: dict | None,
                      field_gt: dict | None, field_baseline: dict | None = None) -> str:
    """세 평가 집합 한 표: held-out 91 / 사고영상 dev 74 / 현장 held-out(evaluate_field 결과; 없으면 미확보로 적는다)."""
    def hl(res, cls, key):
        r = _row(res, cls)
        return "미측정" if r is None or r[key] is None else f"{r[key]} {_ci(r[key + '_ci95'])}"
    nh, nv = "NO-Hardhat", "NO-Safety Vest"
    g = GOALS["primary"]
    L = ["| 평가 집합 | 지표 | 전(v1) | " + cand_label + " | 목표 | 판정 |", "|---|---|---|---|---|---|"]
    if cand is not None or baseline is not None:
        for cls, key, tgt in ((nh, "recall", g[nh]["recall_min"]), (nh, "precision", g[nh]["precision_min"]),
                              (nv, "recall", g[nv]["recall_min"]), (nv, "precision", g[nv]["precision_min"])):
            r = _row(cand, cls); val = None if r is None else r[key]
            verdict = verdict_of(val, tgt, None if r is None else r[key + "_ci95"])
            L.append(f"| held-out 91장(@{(cand or baseline or {}).get('op_conf', 0.35)}) | {cls} {key} | {hl(baseline, cls, key)} | {hl(cand, cls, key)} | ≥{tgt} | {verdict} |")
        bs = None if not baseline else baseline["summary"]["mAP50_all10"]; cs = None if not cand else cand["summary"]["mAP50_all10"]
        L.append(f"| held-out 91장 | 10클래스 mAP@50 | {bs if bs is not None else '미측정'} | {cs if cs is not None else '미측정'} | (참고) | - |")
    # 사고영상 dev 74장 — 전 행은 v1 현장 기준선 리포트 고정값, 후 행은 x4b_score_candidates.score_one 결과가 있을 때만
    d = dev74_cand or {}
    dv = d.get("ppe_recall"); dv_s = "미측정" if dv is None else f"{round(dv * 100, 1) if dv <= 1 else dv}"
    dp = d.get("ppe_precision"); dp_s = "미측정" if dp is None else f"{round(dp * 100, 1) if dp <= 1 else dp}"
    tgt2 = GOALS["secondary"]["dev74_ppe_recall_min"]
    v2 = "미측정" if dv is None else ("달성" if (dv * 100 if dv <= 1 else dv) >= tgt2 else "미달")
    L.append(f"| 사고영상 dev 74장(앱 파이프라인) | PPE 전체 재현율 | {V1_DEV74['ppe_recall']} ({V1_DEV74['ppe_tp']}/{V1_DEV74['ppe_gt']}) | {dv_s} | ≥{tgt2} | {v2} |")
    L.append(f"| 사고영상 dev 74장(앱 파이프라인) | PPE 전체 정밀도 | {V1_DEV74['ppe_precision']} | {dp_s} | (유지) | - |")
    nh_i = d.get("nh_lower"); nh_s = "미측정" if nh_i is None else f"[{round(nh_i * 100, 1)}, {round(d.get('nh_upper', 0) * 100, 1)}]"
    L.append(f"| 사고영상 dev 74장(앱 파이프라인) | NO-Hardhat 재현율 구간 | [{V1_DEV74['nh_interval'][0]}, {V1_DEV74['nh_interval'][1]}] n={V1_DEV74['nh_n']} | {nh_s} | (참고) | - |")
    # 재방문 현장 정답지 — 최종 판정은 여기서만
    if field_gt and "rows" in field_gt:                                  # [2026-09-27] evaluate_field 결과(현장 held-out 300 + 음성)
        fb = field_baseline or {}; n_pos = (field_gt.get("field") or {}).get("n_positive_found", "?")
        for cls in (nh, nv):
            tgt = GOALS["field"][cls]["recall_min"]; r = _row(field_gt, cls)
            L.append(f"| **현장 held-out {n_pos}장(@{field_gt.get('op_conf', 0.35)})** | {cls} recall | {hl(fb, cls, 'recall')} | {hl(field_gt, cls, 'recall')} | ≥{tgt} | "
                     f"{verdict_of(None if r is None else r['recall'], tgt, None if r is None else r['recall_ci95'])} |")
            L.append(f"| 현장 held-out {n_pos}장 | {cls} precision | {hl(fb, cls, 'precision')} | {hl(field_gt, cls, 'precision')} | (유지) | - |")
            L.append(f"| 현장 held-out {n_pos}장 | {cls} AP50 | {'미측정' if not _row(fb, cls) else _row(fb, cls)['ap50']} | {'미측정' if r is None else r['ap50']} | (참고) | - |")
        ng = field_gt.get("negatives") or {}; nb = (fb.get("negatives") or {}) if fb else {}
        mx = GOALS["field"]["neg_fp_rate_max"]; rate = ng.get("neg_fp_rate")

        def neg_cell(d):
            return "미측정" if d.get("neg_fp_rate") is None else f"{d.get('neg_fp_rate')} {_ci(d.get('neg_fp_rate_ci95'))}"
        neg_verdict = "미측정" if rate is None else ("달성" if rate <= mx else "미달")
        L.append(f"| **현장 음성 {ng.get('neg_images', '?')}장** | 프레임 오탐률 % | {neg_cell(nb)} | {neg_cell(ng)} | ≤{mx} | {neg_verdict} |")
    elif field_gt:
        L.append(f"| 재방문 현장 정답지 | {field_gt.get('metric', 'PPE 재현율')} | {field_gt.get('before', '미측정')} | {field_gt.get('after', '미측정')} | {field_gt.get('target', '-')} | {field_gt.get('verdict', '-')} |")
    else:
        L.append("| **재방문 현장 정답지(최종 판정)** | PPE 클래스별 재현율 | **미확보** | **미확보** | 착수 조건: B-finetune | **판정 불가** |")
    return "\n".join(L)


def run_dev74(weights: str) -> dict:
    """사고영상 dev 74장을 앱 파이프라인으로 채점(benchmarks/x4b_score_candidates.score_one). 자료가 없으면 미측정."""
    try:
        sys.path.insert(0, str(_ROOT / "benchmarks"))
        import x4b_score_candidates as x4b  # noqa: PLC0415  (field_eval 자료가 있어야 import 자체가 된다)
        r = x4b.score_one(weights)
        r["status"] = "측정"
        return r
    except Exception as e:  # noqa: BLE001
        return {"status": "미측정", "reason": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="PPE 가중치 비교 하네스 — held-out 91장 + 사고영상 dev 74 + 현장 정답지(미확보) 한 표")
    ap.add_argument("--weights", default=str(_ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"))
    ap.add_argument("--label", default=None, help="비교표의 '후' 열 이름(기본: 가중치 파일명)")
    ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0, help="시험용: 앞 N장만")
    ap.add_argument("--split-rule", choices=("video", "stem"), default="video",
                    help="video=영상 id(확장자 무시)+youtube 묶음 제외(기본, 기준선) · stem=1차 규칙 재현(누출 잔존, 기준선 아님)")
    ap.add_argument("--baseline-json", default=str(BASELINE_JSON), help="'전(v1)' 행 원자료(provenance.md §7-2)")
    ap.add_argument("--out", default=None, help="결과 JSON(기본 benchmarks/results/ppe_compare_<label>.json). 기준선 파일은 덮어쓰지 않는다")
    ap.add_argument("--write-baseline", action="store_true", help="이 결과를 기준선(--baseline-json)으로 저장 — v1 재측정 때만")
    ap.add_argument("--dev74", action="store_true", help="사고영상 dev 74장도 앱 파이프라인으로 채점(느림, field_eval 자료 필요)")
    ap.add_argument("--dev74-json", default=None, help="이미 채점한 dev 74 결과(x4b score_one 형식)를 대신 읽는다")
    ap.add_argument("--field-gt-json", default=None, help="재방문 현장 정답지 결과(있을 때만). 없으면 '미확보'")
    ap.add_argument("--field-heldout", default=None, help="[2026-09-27] 현장 held-out 폴더(field_prelabel+field_split heldout 산출: heldout.json·images·labels·negatives) → 세 번째 집합을 직접 채점")
    ap.add_argument("--field-baseline-json", default=None, help="현장 held-out 의 '전(v1)' 결과(evaluate_field 저장본). 없으면 미측정")
    ap.add_argument("--field-only", action="store_true", help="CSS held-out 91 은 건너뛰고 현장 held-out 만(학습 중 중간 평가용)")
    a = ap.parse_args()
    label = a.label or Path(a.weights).stem
    if a.field_only and not a.field_heldout:
        print("★--field-only 는 --field-heldout 이 필요하다"); return 2

    baseline = json.loads(Path(a.baseline_json).read_text(encoding="utf-8")) if Path(a.baseline_json).exists() else None
    if baseline is None:
        print(f"★기준선 파일 없음: {a.baseline_json} — '전(v1)' 열은 미측정으로 표시")
    cand = None
    if not a.field_only:
        cand = evaluate(a.weights, a.res, a.iou, a.split_rule, a.limit)
        if baseline and a.split_rule == "video" and not a.limit and sorted(baseline["heldout_files"]) != sorted(cand["heldout_files"]):
            print("★경고: 이 실행의 held-out 파일 목록이 기준선과 다르다 — 비교표는 같은 집합이 아니다")
            cand["heldout_mismatch_vs_baseline"] = True
    field_res = None; field_base = None
    if a.field_heldout:
        print("\n현장 held-out 채점 중…")
        field_res = evaluate_field(a.weights, a.field_heldout, a.res, a.iou, a.limit)
        if a.field_baseline_json and Path(a.field_baseline_json).exists():
            field_base = json.loads(Path(a.field_baseline_json).read_text(encoding="utf-8"))

    dev74 = None
    if a.dev74_json:
        dev74 = json.loads(Path(a.dev74_json).read_text(encoding="utf-8"))
    elif a.dev74:
        print("\n사고영상 dev 74장 채점 중(앱 파이프라인)…")
        dev74 = run_dev74(a.weights)
        print(f"  → {dev74.get('status')}" + (f" ({dev74.get('reason')})" if dev74.get("reason") else ""))
    field_gt = field_res or (json.loads(Path(a.field_gt_json).read_text(encoding="utf-8")) if a.field_gt_json else None)

    if cand is not None:
        print(f"\n### held-out {cand['heldout']['heldout_images']}장 — 전(v1) ↔ {label}  (@{cand['op_conf']}, res {a.res}, {cand['device']})")
        print(render_heldout_compare(baseline, cand, label))
    print("\n### 세 평가 집합 — 목표 대비")
    print(render_three_sets(baseline, cand, label, dev74, field_gt, field_base))
    print(f"\n최종 판정: {GOALS['final']}")

    out = {"candidate_label": label, "candidate": cand, "baseline_json": a.baseline_json, "goals": GOALS,
           "goal_check": goal_check(cand) if cand else [], "dev74_candidate": dev74, "dev74_v1": V1_DEV74,
           "field_gt": field_gt or "미확보", "field_goal_check": field_goal_check(field_res), "field_baseline_json": a.field_baseline_json}
    out_path = Path(a.out) if a.out else _ROOT / "benchmarks" / "results" / f"ppe_compare_{label}.json"
    if a.write_baseline and cand is not None:
        Path(a.baseline_json).write_text(json.dumps(cand, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기준선 갱신: {a.baseline_json}")
    elif out_path.resolve() == Path(a.baseline_json).resolve():
        print("★기준선 파일은 --write-baseline 없이는 덮어쓰지 않는다"); return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_img = cand["heldout"]["heldout_images"] if cand else (field_res or {}).get("field", {}).get("n_positive_found", 0)
    dev = (cand or field_res or {}).get("device", "?"); el = (cand or field_res or {}).get("elapsed_s", 0)
    print(f"\n저장: {out_path} · {n_img}장 · {dev} · {el}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
