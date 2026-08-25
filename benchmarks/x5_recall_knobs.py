#!/usr/bin/env python3
"""[X5] 재학습 없이 재현율을 올리는 손잡이 3개 — dev 셋 실측.

★절대 규칙(사용자 지시 2026-08-25):
  · **튜닝은 dev(74장)로만** 한다. test(35장)는 **최종 확인 1회**만 — dev 로 고른 설정을
    test 에 단 한 번 적용해 일반화되는지 본다. test 를 보며 조정하면 그 숫자는 죽는다.
  · 각 실험은 **독립적으로**: 기준선 → 변경 1개 → 측정.

★기존 방법론 준수(benchmarks/person_conf_sweep.py):
  임계마다 **실제로 추론을 다시 돌린다**(점수 사후 필터링으로 근사하지 않는다) —
  NMS·포함억제·앙상블 병합이 임계에 따라 달라지기 때문이다.
  모델은 한 번만 로드하고 손잡이만 바꿔 반복한다.

★측정만 한다 — config/tuning.yaml·vision.yaml 을 **수정하지 않는다**(규칙6).
  운용값 변경은 이 표를 보고 사람이 결정한다.

사용:
    python benchmarks/x5_recall_knobs.py --exp conf      # 실험1 클래스별 임계
    python benchmarks/x5_recall_knobs.py --exp track     # 실험1-b 추적 스폰 임계
    python benchmarks/x5_recall_knobs.py --exp imgsz     # 실험2 해상도
    python benchmarks/x5_recall_knobs.py --exp ensemble  # 실험3 yolo11m 3중
    python benchmarks/x5_recall_knobs.py --exp confirm --split test   # ★최종 1회
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cv2  # noqa: E402
import vision_loader  # noqa: E402
from agents.guard import GuardAgent  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

_FE = _ROOT / "data" / "field_eval"
IOU_THR = 0.5
# 평가 대상 — 표본이 의미 있는 클래스만(그 외는 "표본 부족"으로 비운다)
CLASSES = ["person", "NO-Safety-Vest", "NO-Hardhat", "Hardhat"]
SMALL_BOX_H = 0.10          # 화면 높이 대비 이 미만이면 '작은 박스'(원거리 대리 지표)


def _gt_names() -> list[str]:
    return (_FE / "classes.txt").read_text(encoding="utf-8").split()


def _split(name: str) -> list[str]:
    sp = json.loads((_FE / "dev_test_split.json").read_text(encoding="utf-8"))
    return list(sp[name])


def _load_gt(frames: list[str]) -> dict[str, list[tuple[str, list[float]]]]:
    """프레임별 GT: [(클래스명, [x1,y1,x2,y2] 정규화)]."""
    names = _gt_names()
    gt: dict[str, list[tuple[str, list[float]]]] = {}
    for fn in frames:
        stem = Path(fn).stem
        f = _FE / "labels" / f"{stem}.txt"
        boxes = []
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                p = line.split()
                if len(p) < 5:
                    continue
                ci, cx, cy, w, h = int(p[0]), *(float(v) for v in p[1:5])
                boxes.append((names[ci] if ci < len(names) else f"c{ci}",
                              [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]))
        gt[stem] = boxes
    return gt


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _match(preds: list[tuple[str, list[float], float]],
           gts: list[tuple[str, list[float]]], cls: str) -> tuple[int, int, int, int, int]:
    """한 프레임·한 클래스의 (TP, FP, FN, 작은박스 GT, 작은박스 TP). 탐욕 매칭(conf 내림차순)."""
    P = sorted([p for p in preds if p[0] == cls], key=lambda x: -x[2])
    G = [g for g in gts if g[0] == cls]
    used = set()
    tp = 0
    small_gt = sum(1 for g in G if (g[1][3] - g[1][1]) < SMALL_BOX_H)
    small_tp = 0
    for _lbl, pb, _c in P:
        best, bi = 0.0, -1
        for i, (_gl, gb) in enumerate(G):
            if i in used:
                continue
            v = _iou(pb, gb)
            if v > best:
                best, bi = v, i
        if best >= IOU_THR and bi >= 0:
            used.add(bi)
            tp += 1
            if (G[bi][1][3] - G[bi][1][1]) < SMALL_BOX_H:
                small_tp += 1
    return tp, len(P) - tp, len(G) - tp, small_gt, small_tp


def _wilson(k: int, n: int) -> tuple[float, float]:
    """95% 윌슨 신뢰구간 — 작은 표본에서 정규근사보다 정직하다."""
    if n == 0:
        return (0.0, 0.0)
    from math import sqrt
    z = 1.959964
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, (c - hw)) * 100, min(1.0, (c + hw)) * 100)


def _by_video(frames: list[str]) -> dict[str, list[str]]:
    """★프레임을 비디오별·시간순으로 묶는다.

    ★[X5, 2026-08-25] 이게 없으면 person 측정이 통째로 무효가 된다.
      운영은 `track.algo=bytetrack` 인데, ByteTrack 은 **첫 프레임에서 person 을 전부 버린다**
      (실측: 입력 4건 → 출력 0건, 2프레임째부터 3건). `detect_isolated`(프레임마다 새 track_key)로
      재면 person 이 **항상 0건**이 되어 재현율 0% 라는 거짓 수치가 나온다.
      field_eval 프레임은 4~5개 영상에서 1초 간격으로 뽑은 것이라 **영상 안에서는 연속**이다 —
      영상별 track_key 로 시간순 입력해야 운영에 가깝다.
      ⚠그래도 **1fps 표본**이라 운영(2fps)보다 추적에 불리하다(이 차이는 결과 해석에 반영할 것).
    """
    import re
    out: dict[str, list[tuple[int, str]]] = {}
    for fn in frames:
        m = re.match(r"(.+)_(\d+)ms\.jpg", fn)
        if not m:
            out.setdefault("_misc", []).append((0, fn))
            continue
        out.setdefault(m.group(1), []).append((int(m.group(2)), fn))
    return {v: [f for _, f in sorted(items)] for v, items in out.items()}


def run_once(guard, frames: list[str], gt: dict, detectors: list[str],
             sequential: bool = True) -> dict:
    """한 설정으로 전 프레임 추론 → 클래스별 집계 + 지연.

    sequential=True 면 **영상별 시간순**으로 넣고 track_key 를 영상 단위로 준다(운영 근사).
    """
    agg = {c: [0, 0, 0, 0, 0] for c in CLASSES}      # tp fp fn small_gt small_tp
    lat: list[float] = []
    ordered: list[tuple[str, str]] = []
    if sequential:
        for vid, fns in _by_video(frames).items():
            ordered += [(vid, f) for f in fns]
    else:
        ordered = [("", f) for f in frames]
    for i, (vid, fn) in enumerate(ordered):
        img = cv2.imread(str(_FE / "frames" / fn))
        if img is None:
            continue
        t0 = time.perf_counter()
        out = (guard.detect(img, detectors=detectors, track_key=f"x5:{vid}") if sequential
               else detect_isolated(guard, img, detectors=detectors))
        dt = (time.perf_counter() - t0) * 1000.0
        if i >= 3:                                    # 워밍업 3장 제외
            lat.append(dt)
        preds = [(str(d.get("label", "")), d.get("bbox") or [0, 0, 0, 0], float(d.get("conf", 0)))
                 for d in out.get("detections", [])]
        for c in CLASSES:
            r = _match(preds, gt.get(Path(fn).stem, []), c)
            for j in range(5):
                agg[c][j] += r[j]
    lat.sort()
    return {"agg": agg,
            "p50": lat[len(lat) // 2] if lat else 0.0,
            "p95": lat[int(len(lat) * 0.95)] if lat else 0.0,
            "max": lat[-1] if lat else 0.0}


def fmt(agg: dict, cls: str) -> dict:
    tp, fp, fn, sgt, stp = agg[cls]
    prec = tp / (tp + fp) * 100 if (tp + fp) else 0.0
    rec = tp / (tp + fn) * 100 if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    lo, hi = _wilson(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "n_gt": tp + fn, "prec": prec, "rec": rec, "f1": f1,
            "rec_lo": lo, "rec_hi": hi, "small_gt": sgt, "small_tp": stp,
            "small_rec": (stp / sgt * 100 if sgt else None)}


def _guard() -> GuardAgent:
    return GuardAgent(vision_loader.load_vision("safety"))


def _print_row(tag: str, res: dict, cls: str) -> None:
    m = fmt(res["agg"], cls)
    sr = f"{m['small_rec']:.1f}" if m["small_rec"] is not None else "  — "
    print(f"  {tag:<22}{m['prec']:>7.1f}{m['rec']:>8.1f}{m['f1']:>7.1f}"
          f"  [{m['rec_lo']:.0f},{m['rec_hi']:.0f}]{m['tp']:>6}{m['fp']:>5}{m['fn']:>5}"
          f"{sr:>8}{res['p50']:>8.0f}")


def _header(title: str, cls: str, n_gt: int) -> None:
    print(f"\n■ {title} — 클래스 {cls} (GT {n_gt}건)")
    print(f"  {'설정':<22}{'정밀도':>7}{'재현율':>8}{'F1':>7}{'  재현율95%CI':<12}"
          f"{'TP':>6}{'FP':>5}{'FN':>5}{'작은박스R':>8}{'p50ms':>8}")


def exp_conf(frames, gt, args):
    """실험1 — 클래스별 운용 임계 스윕(dev)."""
    g = _guard()
    base_person = g.DETECTOR_CONF["person"]
    base_ppe = g.DETECTOR_CONF["ppe"]
    confs = [round(x, 2) for x in args.confs]
    print(f"\n기준선: person={base_person} ppe={base_ppe} imgsz={g.IMGSZ}")

    _header("실험1-A person 임계 스윕", "person", 0)
    for c in confs:
        g.DETECTOR_CONF = {**g.DETECTOR_CONF, "person": c}
        g._models = {}                      # 임계는 추론 인자라 재로드 불필요하나 상태 초기화
        g = _reload_keep(g, {"person": c})
        res = run_once(g, frames, gt, ["person", "ppe"])
        _print_row(f"person={c}{' ★현재' if c == base_person else ''}", res, "person")

    for cls in ("NO-Safety-Vest", "NO-Hardhat", "Hardhat"):
        _header("실험1-B ppe 임계 스윕", cls, 0)
        for c in confs:
            g = _reload_keep(g, {"ppe": c})
            res = run_once(g, frames, gt, ["person", "ppe"])
            _print_row(f"ppe={c}{' ★현재' if c == base_ppe else ''}", res, cls)


def _reload_keep(g: GuardAgent, conf_over: dict) -> GuardAgent:
    """모델은 유지한 채 임계만 바꾼다(재로드 비용 회피)."""
    g.DETECTOR_CONF = {**g.DETECTOR_CONF, **conf_over}
    return g


def exp_track(frames, gt, args):
    """실험1-b — 추적 스폰 임계(BYTETRACK_ACTIVATION) 스윕."""
    print("\n■ 실험1-b 추적 스폰 임계 — person")
    print("  ★현재 BYTETRACK_ACTIVATION=None → person 운용 임계(0.40)에 자동 연동됨")
    print("     (하드코딩 0.70 이던 회귀는 [PA, 2026-08-13] 에 이미 수정됐다)")
    _header("스폰 임계 스윕", "person", 0)
    for act in args.acts:
        g = _guard()
        g.BYTETRACK_ACTIVATION = None if act < 0 else float(act)
        res = run_once(g, frames, gt, ["person", "ppe"])
        tag = "연동(0.40)" if act < 0 else f"activation={act}"
        _print_row(tag, res, "person")


def exp_imgsz(frames, gt, args):
    """실험2 — 해상도 교환표."""
    print("\n■ 실험2 해상도 — 재현율(특히 작은 박스) vs 추론 시간")
    _header("imgsz 스윕", "person", 0)
    rows = []
    for sz in args.sizes:
        g = _guard()
        g.IMGSZ = int(sz)
        g._models = {}                       # ★RF-DETR 은 로드 시 해상도를 컴파일 고정 → 재로드 필수
        res = run_once(g, frames, gt, ["person", "ppe"])
        _print_row(f"imgsz={sz}{' ★현재' if sz == 384 else ''}", res, "person")
        rows.append((sz, res))
    print("\n  [참고] 카메라당 수용 대수 ≈ 1000ms / (검출주기 500ms 내 추론시간) — 아래 §교환표")
    for sz, res in rows:
        cap = 500.0 / res["p95"] if res["p95"] else 0
        print(f"    imgsz={sz}: p95={res['p95']:.0f}ms → 검출주기 500ms 기준 동시 {cap:.1f}대")


def exp_ensemble(frames, gt, args):
    """실험3 — yolo11m 을 person 앙상블에 추가(실험 분기, 기존 병합 미변경)."""
    print("\n■ 실험3 person 3중 앙상블(+yolo11m) — ★기존 병합 로직은 건드리지 않는다")
    _header("앙상블", "person", 0)
    g = _guard()
    base = run_once(g, frames, gt, ["person", "ppe"])
    _print_row("현행 2중(person+ppe)", base, "person")

    # yolo11m 을 별도 어댑터로 직접 돌려 person 박스를 합친다(실험 분기)
    from agents.guard import JUNK_LABELS, LABEL_NORMALIZE
    from detectors.yolo_adapter import YoloDetector
    w = _ROOT / "vigent-core" / "weights" / "yolo11m.pt"
    if not w.exists():
        print("  ❌ yolo11m.pt 없음 — 실험 불가")
        return
    y = YoloDetector(str(w), g.device, g.IMGSZ, LABEL_NORMALIZE, JUNK_LABELS)
    agg = {c: [0, 0, 0, 0, 0] for c in CLASSES}
    lat = []
    for i, fn in enumerate(frames):
        img = cv2.imread(str(_FE / "frames" / fn))
        if img is None:
            continue
        t0 = time.perf_counter()
        out = detect_isolated(g, img, detectors=["person", "ppe"])
        extra = y.detect(img, conf=g.DETECTOR_CONF["person"], imgsz=g.IMGSZ, augment=False)
        dt = (time.perf_counter() - t0) * 1000.0
        if i >= 3:
            lat.append(dt)
        preds = [(str(d.get("label", "")), d.get("bbox") or [0, 0, 0, 0], float(d.get("conf", 0)))
                 for d in out.get("detections", [])]
        # 기존 person 박스와 IoU 0.5 이상 겹치지 않는 yolo person 만 추가(단순 병합)
        exist = [p[1] for p in preds if p[0] == "person"]
        for d in extra:
            if str(d.get("label", "")).lower() != "person":
                continue
            bb = d.get("bbox") or [0, 0, 0, 0]
            if all(_iou(bb, e) < 0.5 for e in exist):
                preds.append(("person", bb, float(d.get("conf", 0))))
        for c in CLASSES:
            r = _match(preds, gt.get(Path(fn).stem, []), c)
            for j in range(5):
                agg[c][j] += r[j]
    lat.sort()
    res = {"agg": agg, "p50": lat[len(lat) // 2] if lat else 0,
           "p95": lat[int(len(lat) * 0.95)] if lat else 0, "max": lat[-1] if lat else 0}
    _print_row("3중(+yolo11m)", res, "person")
    print(f"\n  추가 비용: p50 {base['p50']:.0f} → {res['p50']:.0f}ms "
          f"(+{res['p50'] - base['p50']:.0f}ms)")


def exp_confirm(frames, gt, args):
    """★최종 확인 — dev 로 고른 설정을 지정 split 에 **1회만** 적용."""
    print(f"\n■ 최종 확인 (split={args.split}) — ★이 실행은 1회로 끝낸다")
    g = _guard()
    if args.person_conf:
        g.DETECTOR_CONF = {**g.DETECTOR_CONF, "person": args.person_conf}
    if args.ppe_conf:
        g.DETECTOR_CONF = {**g.DETECTOR_CONF, "ppe": args.ppe_conf}
    if args.imgsz:
        g.IMGSZ = args.imgsz
        g._models = {}
    print(f"  적용: person={g.DETECTOR_CONF['person']} ppe={g.DETECTOR_CONF['ppe']} imgsz={g.IMGSZ}")
    res = run_once(g, frames, gt, ["person", "ppe"])
    for c in CLASSES:
        m = fmt(res["agg"], c)
        if m["n_gt"] < 15:
            print(f"  {c:<16} GT {m['n_gt']:>3}건 — ★표본 부족(수치 생략)")
            continue
        _header("확인 결과", c, m["n_gt"])
        _print_row("적용본", res, c)


# ─────────────────────────────────────────────────────────────────────────────
# [X5-①] 트래커 5개 후보 — 추적이 검출을 얼마나 버리는가를 후보별로 비교한다.
#   ★운영 코드는 건드리지 않는다. 각 후보는 `_track` 을 감싸는 **실험 분기**로만 구현한다.
def _apply_candidate(g, name: str, passthru_conf: float = 0.50):
    """후보 설정을 guard 인스턴스에 적용하고, 필요하면 _track 을 감싼다."""
    import agents.guard as GM
    orig = GM.GuardAgent._track
    stats = {"pre": 0, "post": 0, "readded": 0, "tids": set(), "no_tid": 0}

    if name == "bytetrack":
        wrapper = None
    elif name == "minframes0":
        g.BYTETRACK_MIN_FRAMES = 0
        wrapper = None
    elif name == "iou":
        g.TRACK_ALGO = "iou"
        wrapper = None
    elif name == "hybrid":
        # ByteTrack 결과를 쓰되, **ByteTrack 이 버린 person 을 IoU 추적으로 한 번 더 건진다.**
        #   ID 는 ByteTrack 것을 우선하고, 건진 건에는 IoU 트랙 id 를 준다.
        def wrapper(self, fresh, key):
            stats["pre"] += sum(1 for d in fresh if str(d.get("label", "")).lower() == "person")
            bt = orig(self, fresh, key)
            kept = {id(d) for d in bt}
            missing = [d for d in fresh if id(d) not in kept
                       and str(d.get("label", "")).lower() == "person"]
            if missing:
                algo, self.TRACK_ALGO = self.TRACK_ALGO, "iou"
                try:
                    extra = orig(self, missing, key + ":iou")
                finally:
                    self.TRACK_ALGO = algo
                stats["readded"] += len(extra)
                bt = list(bt) + list(extra)
            stats["post"] += sum(1 for d in bt if str(d.get("label", "")).lower() == "person")
            return bt
    elif name == "passthrough":
        # ★검출 통과 — 트랙 확정 여부와 무관하게 **고신뢰 검출을 그대로 통과**시킨다.
        #   트랙 ID 는 되는 것만 쓴다(없으면 tid 없음). 경보 재현율을 추적기 성능에서 분리한다.
        def wrapper(self, fresh, key):
            stats["pre"] += sum(1 for d in fresh if str(d.get("label", "")).lower() == "person")
            tracked = orig(self, fresh, key)
            kept = {id(d) for d in tracked}
            out = list(tracked)
            for d in fresh:
                if id(d) in kept:
                    continue
                if str(d.get("label", "")).lower() != "person":
                    continue
                if float(d.get("conf", 0)) < passthru_conf:
                    continue
                d = {**d, "tid": None, "passthrough": True}   # ★ID 없음을 명시
                out.append(d)
                stats["readded"] += 1
                stats["no_tid"] += 1
            stats["post"] += sum(1 for d in out if str(d.get("label", "")).lower() == "person")
            return out
    else:
        raise ValueError(name)
    return wrapper, orig, stats


def exp_tracker(frames, gt, args):
    """★① 트래커 5개 후보 비교 — dev."""
    import agents.guard as GM
    cands = [("bytetrack", "현행 bytetrack ★운영"), ("minframes0", "MIN_FRAMES=0"),
             ("iou", "iou 복귀"), ("hybrid", "하이브리드(BT+IoU회수)"),
             ("passthrough", f"검출통과(conf≥{args.passthru})")]
    print("\n■ ① 트래커 후보 비교 — dev person (GT 157건) · 순차 입력")
    print(f"  {'후보':<26}{'정밀도':>8}{'재현율':>8}{'F1':>7}{'  재현율CI':<12}"
          f"{'TP':>5}{'FP':>5}{'작은R':>7}{'고유ID':>7}{'ID없음':>7}{'p50':>7}")
    results = {}
    for key, label in cands:
        g = _guard()
        wrapper, orig, stats = _apply_candidate(g, key, args.passthru)
        if wrapper is not None:
            GM.GuardAgent._track = wrapper
        try:
            r = run_once(g, frames, gt, ["person", "ppe"])
        finally:
            GM.GuardAgent._track = orig
        m = fmt(r["agg"], "person")
        tids, no_tid = _count_ids(g, frames, gt, key, args.passthru)
        sr = f"{m['small_rec']:.0f}" if m["small_rec"] is not None else "—"
        print(f"  {label:<26}{m['prec']:>8.1f}{m['rec']:>8.1f}{m['f1']:>7.1f}"
              f"  [{m['rec_lo']:.0f},{m['rec_hi']:.0f}]{m['tp']:>7}{m['fp']:>5}{sr:>7}"
              f"{tids:>7}{no_tid:>7}{r['p50']:>7.0f}")
        results[key] = (m, r, tids, no_tid)
    return results


def _count_ids(g_unused, frames, gt, key, passthru):
    """후보별 고유 track id 수(ID 스위치 대리 지표)와 ID 없는 검출 수."""
    import agents.guard as GM
    g = _guard()
    wrapper, orig, stats = _apply_candidate(g, key, passthru)
    if wrapper is not None:
        GM.GuardAgent._track = wrapper
    tids: set = set()
    no_tid = 0
    try:
        for vid, fns in _by_video(frames).items():
            for fn in fns:
                img = cv2.imread(str(_FE / "frames" / fn))
                if img is None:
                    continue
                o = g.detect(img, detectors=["person", "ppe"], track_key=f"id:{vid}")
                for d in o.get("detections", []):
                    if str(d.get("label", "")).lower() != "person":
                        continue
                    if d.get("tid") is None:
                        no_tid += 1
                    else:
                        tids.add((vid, int(d["tid"])))
    finally:
        GM.GuardAgent._track = orig
    return len(tids), no_tid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True,
                    choices=["conf", "track", "tracker", "imgsz", "ensemble", "confirm"])
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--confs", type=float, nargs="+",
                    default=[0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80])
    ap.add_argument("--acts", type=float, nargs="+", default=[-1, 0.28, 0.35, 0.50, 0.70])
    ap.add_argument("--sizes", type=int, nargs="+", default=[384, 512, 640])
    ap.add_argument("--person-conf", type=float, default=0.0)
    ap.add_argument("--ppe-conf", type=float, default=0.0)
    ap.add_argument("--imgsz", type=int, default=0)
    ap.add_argument("--passthru", type=float, default=0.50,
                    help="검출통과 후보의 고신뢰 기준")
    args = ap.parse_args()

    if args.exp != "confirm" and args.split != "dev":
        print("★튜닝 실험은 dev 로만 한다(사용자 지시). --exp confirm 에서만 test 를 쓴다.")
        return 2

    frames = _split(args.split)
    gt = _load_gt(frames)
    n = {c: sum(1 for f in frames for lbl, _ in gt[Path(f).stem] if lbl == c) for c in CLASSES}
    print(f"평가셋: field_eval/{args.split} {len(frames)}장 · GT {n}")
    print("★측정만 한다 — tuning.yaml/vision.yaml 을 수정하지 않는다.")

    {"conf": exp_conf, "track": exp_track, "tracker": exp_tracker, "imgsz": exp_imgsz,
     "ensemble": exp_ensemble, "confirm": exp_confirm}[args.exp](frames, gt, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
