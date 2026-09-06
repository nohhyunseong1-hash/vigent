"""ppe_eval.py — 클래스 인식 PPE 평가(클래스별 정밀도·재현율·mAP@0.5).

eval_harness.py 의 _load_gt() 는 라벨의 클래스 인덱스를 무시하므로(단일 클래스 전용),
PPE 처럼 다중 클래스 셋은 클래스별로 GT/예측을 매칭해야 한다. 이 스크립트가 그 역할을 한다.
  · GT 클래스명(data.yaml names[idx]) 과 예측 라벨을 정규화(소문자·영숫자만)해 매칭
  · guard.detect(detectors=["ppe"]) 예측을 사용 → '배포 파이프라인' 실측(가드 임계 반영)
  · IoU≥0.5 매칭 → 클래스별 TP/FP/FN → P·R, 신뢰도 내림차순 11-point AP@0.5

사용: python tools/ml/ppe_eval.py --set data/datasets/css_safety/test
⚠ 모델·원본 불변(읽기만). 라벨 신뢰성(완전·정확)에 점수가 좌우됨.
※ 2026-09-06 감사: 동명의 구 `tools/ppe_eval.py`(ultralytics YOLO .val(), AGPL, mac 절대경로의
   존재하지 않는 best.pt 참조)를 삭제하고 이 파일을 단일본으로 확정. 옛 파일의 mAP50-95 는
   ultralytics 전용이라 흡수하지 않음(배포 검출기는 RF-DETR). 복구: git show d2fea51:tools/ppe_eval.py
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "vigent-core"))

# 배포 PPE 모델(ppe_css_v1)의 대상 6클래스
TARGETS = ["Hardhat", "NO-Hardhat", "Mask", "NO-Mask", "Safety Vest", "NO-Safety Vest"]


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _ap50(pairs, n_gt):
    pairs = sorted(pairs, key=lambda x: -x[0])
    tp = fp = 0
    pts = []
    for _, is_tp in pairs:
        tp += is_tp
        fp += (not is_tp)
        pts.append((tp / n_gt if n_gt else 0.0, tp / (tp + fp)))
    ap = 0.0
    for t in [i / 10 for i in range(11)]:
        ps = [p for r, p in pts if r >= t]
        ap += (max(ps) if ps else 0.0) / 11
    return ap * 100


def _names(set_dir):
    """data.yaml 의 names 리스트를 찾는다(셋 폴더 또는 상위)."""
    import yaml
    for cand in (os.path.join(set_dir, "data.yaml"),
                 os.path.join(os.path.dirname(set_dir), "data.yaml")):
        if os.path.exists(cand):
            y = yaml.safe_load(open(cand, encoding="utf-8"))
            if isinstance(y.get("names"), list):
                return y["names"]
    raise SystemExit("data.yaml(names) 를 찾지 못함")


def evaluate(set_dir):
    import cv2
    import main
    from isolated_detect import detect_isolated
    names = _names(set_dir)
    nt = {t: _norm(t) for t in TARGETS}
    bundle = main.STATE.get(main.DEFAULT_THEME) or main._load_theme(main.DEFAULT_THEME)
    guard = bundle["agents"].get("Guard")
    imgs = sorted(glob.glob(os.path.join(set_dir, "images", "*")))

    gt_cnt = {t: 0 for t in TARGETS}
    tpc = {t: 0 for t in TARGETS}
    fpc = {t: 0 for t in TARGETS}
    ap_pairs = {t: [] for t in TARGETS}
    for imgp in imgs:
        base = os.path.splitext(os.path.basename(imgp))[0]
        lp = os.path.join(set_dir, "labels", base + ".txt")
        gts = {t: [] for t in TARGETS}
        if os.path.exists(lp):
            for line in open(lp):
                p = line.split()
                if len(p) < 5:
                    continue
                ci = int(float(p[0]))
                nm = names[ci] if ci < len(names) else str(ci)
                for t in TARGETS:
                    if _norm(nm) == nt[t]:
                        cx, cy, w, h = map(float, p[1:5])
                        gts[t].append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
                        gt_cnt[t] += 1
        img = cv2.imread(imgp)
        if img is None:
            continue
        H, W = img.shape[:2]
        # 2026-08: 구 `guard._tracks = []`는 존재하지 않는 속성이라 죽은 코드였다(진짜 상태는
        #   `_tracks_by_key`) — 이미지마다 추적기가 실제로는 안 비워지고 있었다.
        out = detect_isolated(guard, img, detectors=["ppe"])
        preds = {t: [] for t in TARGETS}
        for d in out.get("detections", []):
            nl = _norm(d.get("label", ""))
            bb = d.get("bbox")
            if not bb:
                continue
            x1, y1, x2, y2 = bb
            if max(x1, y1, x2, y2) > 1.5:      # 픽셀좌표면 정규화
                x1, y1, x2, y2 = x1 / W, y1 / H, x2 / W, y2 / H
            for t in TARGETS:
                if nl == nt[t]:
                    preds[t].append(([x1, y1, x2, y2], d.get("conf", 0)))
        for t in TARGETS:
            ps = sorted(preds[t], key=lambda x: -x[1])
            matched = set()
            for bb, cf in ps:
                best, bi = -1.0, -1
                for i, g in enumerate(gts[t]):
                    if i in matched:
                        continue
                    v = _iou(bb, g)
                    if v > best:
                        best, bi = v, i
                is_tp = best >= 0.5 and bi >= 0
                if is_tp:
                    matched.add(bi)
                    tpc[t] += 1
                else:
                    fpc[t] += 1
                ap_pairs[t].append((cf, is_tp))

    print(f"평가셋: {set_dir} | 이미지 {len(imgs)}장 | 모델: ppe_css_v1.pt(ppe 슬롯) | IoU≥0.5")
    print(f"{'클래스':16s}{'GT':>5s}{'TP':>5s}{'FP':>5s}{'FN':>5s}{'P%':>7s}{'R%':>7s}{'mAP50%':>8s}")
    for t in TARGETS:
        ng, tp, fp = gt_cnt[t], tpc[t], fpc[t]
        fn = ng - tp
        P = 100 * tp / (tp + fp) if (tp + fp) else 0.0
        R = 100 * tp / ng if ng else 0.0
        ap = _ap50(ap_pairs[t], ng)
        print(f"{t:16s}{ng:5d}{tp:5d}{fp:5d}{fn:5d}{P:7.1f}{R:7.1f}{ap:8.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="data/datasets/css_safety/test")
    args = ap.parse_args()
    evaluate(os.path.join(_ROOT, args.set))
