#!/usr/bin/env python3
"""scripts/eval/classify_field_drops.py — 현장 2fps 데이터에서 '추적이 버린 검출'을 원인별로 분류(R-1·R-2).

배경(2026-09-22): dev(1fps 정지프레임)로 잰 "추적이 검출의 29.3%p 를 버린다" 가 운영 조건을
  대표하지 못한다는 것이 `benchmarks/b_passthru_2fps_check.py` 현장 실행으로 드러났다
  (학원 34분·1.88fps 에서 손실률 3.4~5.2%). 그래서 **현장 데이터로** 원인을 가른다.

R-1: τ 스윕 결과 + 스크립트가 미리 선언한 판정 기준을 JSON 으로 남긴다.
R-2: τ 기준으로 버려진 건 각각을 앞뒤 프레임과 대조해 분류한다.

  A. 확정 지연 — t+1 또는 t+2 에서 같은 사람이 tid 를 받음(무해, 경보 0.5~1초 지연)
  B. 검출 깜빡임 — t±2 안에 검출 자체가 없음(검출기 문제, 추적기로 못 고침)
  C. 반복 탈락 — t+1·t+2 에 검출은 있으나 계속 tid 없음(추적기 문제)
  D. 트랙 종료 — t-1 에 tid 가 있었고 t 에서 끊김(매칭 실패 또는 소멸)
  E. 기타

★'버림' 정의는 benchmarks/b_passthru_2fps_check.py 와 동일하게 맞춘다
  (fresh person conf>=τ 중, 같은 프레임 tracks person 과 IoU < TRACK_IOU 0.45 인 것).
★운영 코드 무수정 — 이미 기록된 jsonl 만 읽는다(규칙 6).
★판정하지 않는다. 표만 만든다(규칙 7).

재현:
    python scripts/eval/classify_field_drops.py \
        --data runs/field_20260827/track_debug.jsonl \
        --json audit/passthru_field_20260922.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent

TRACK_IOU = 0.45        # b_passthru_2fps_check.py 와 동일(같은 객체로 볼 겹침)
SAME_IOU = 0.30         # 앞뒤 프레임에서 '같은 사람' 판정 IoU — 지시받은 값
SAME_DIST = 0.15        # 같은 사람 판정 중심거리 — 지시받은 값
WINDOW = 2              # t±2 프레임까지 본다
CLIP_H = 0.95           # 이 이상이면 세로가 화면에 잘린 박스로 본다(v2)
VERSION = "v2"          # v1 의 B 분류 결함(고정 거리 기준) 정정본
TAUS = [0.4, 0.5, 0.6]

# 스크립트가 미리 선언한 판정 기준(b_passthru_2fps_check.py docstring) — 결과 파일에 함께 싣는다.
DECLARED_CRITERIA = {
    "선언일": "2026-08-25",
    "출처": "benchmarks/b_passthru_2fps_check.py docstring",
    "기준": [
        "2프레임 이상 구간이 전체의 30% 이상 → passthrough 를 그대로 켠다(디바운스 무수정으로 경보가 살아남)",
        "30% 미만이지만 0% 는 아님 → 부분 이득. 켜되 경보 증가를 현장에서 재확인",
        "여전히 전부 단발(2프레임 이상 0%) → 디바운스 완화를 그때 재검토",
        "표본이 20분 미만이거나 버려진 박스가 30건 미만 → '측정 불충분', 현행 유지",
    ],
}


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _center(b) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _dist(a, b) -> float:
    ax, ay = _center(a)
    bx, by = _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def same_person(a, b) -> bool:
    """앞뒤 프레임에서 같은 사람으로 볼 것인가 — **박스 크기에 비례하는** 기준(v2).

    ★v1 결함(2026-09-22 발견): 중심거리를 **고정 0.15** 로 봐서, 카메라 앞을 가로지르는
      큰 박스(폭 0.2~0.3)가 프레임당 0.2 이동하면 '다른 사람' 으로 걸러졌다. 그 결과
      B(검출 깜빡임) 6건이 실제로는 앞뒤에 검출이 있는데도 '없음' 으로 분류됐다
      (`audit/b_items_qualitative_20260922.md`). 큰 박스일수록 같은 이동량이 더 작은
      상대 변위이므로 기준도 폭에 비례해야 한다.

    v2 기준:
      IoU >= SAME_IOU  **또는**  중심거리 <= max(SAME_DIST, 0.6 × max(폭_t, 폭_t+1))
      단 클리핑 박스(h >= CLIP_H)는 세로가 잘려 세로 중심이 의미 없으므로
      **가로 중심거리만** 본다.
    """
    if _iou(a, b) >= SAME_IOU:
        return True
    wa, wb = a[2] - a[0], b[2] - b[0]
    thr = max(SAME_DIST, 0.6 * max(wa, wb))
    ha, hb = a[3] - a[1], b[3] - b[1]
    if ha >= CLIP_H or hb >= CLIP_H:
        return abs(_center(a)[0] - _center(b)[0]) <= thr      # 세로 무시 — 잘린 박스
    return _dist(a, b) <= thr


def persons(row: dict, kind: str, conf: float = 0.0) -> list[dict]:
    out = []
    for d in (row.get(kind) or []):
        if str(d.get("label", "")).lower() != "person":
            continue
        if kind == "fresh" and float(d.get("conf", 0)) < conf:
            continue
        out.append(d)
    return out


def sweep(rows: list[dict], tau: float) -> dict[str, Any]:
    """b_passthru_2fps_check.py 와 같은 방식의 τ 스윕(결과 재현용)."""
    per_frame: list[bool] = []
    n_drop = n_fresh = 0
    for r in rows:
        fr = persons(r, "fresh", tau)
        tb = [t.get("bbox") or [0, 0, 0, 0] for t in persons(r, "tracks")]
        n_fresh += len(fr)
        drop = [d for d in fr if all(_iou(d.get("bbox") or [0, 0, 0, 0], b) < TRACK_IOU for b in tb)]
        n_drop += len(drop)
        per_frame.append(bool(drop))
    runs: list[int] = []
    cur = 0
    for hit in per_frame:
        if hit:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    dist = Counter(runs)
    ge2 = sum(c for length, c in dist.items() if length >= 2)
    return {"tau": tau, "n_fresh_person": n_fresh, "n_dropped": n_drop,
            "drop_pct": round(n_drop / max(n_fresh, 1) * 100, 1),
            "runs_total": len(runs), "runs_dist": {str(k): v for k, v in sorted(dist.items())},
            "runs_ge2": ge2, "runs_ge2_pct": round(ge2 / max(len(runs), 1) * 100, 1),
            "runs_ge3": sum(c for length, c in dist.items() if length >= 3)}


def classify(rows: list[dict], tau: float) -> list[dict]:
    """버려진 건 각각을 앞뒤 프레임과 대조해 A~E 로 분류한다."""
    out: list[dict] = []
    for i, r in enumerate(rows):
        tb = [t.get("bbox") or [0, 0, 0, 0] for t in persons(r, "tracks")]
        for d in persons(r, "fresh", tau):
            box = d.get("bbox") or [0, 0, 0, 0]
            if any(_iou(box, b) >= TRACK_IOU for b in tb):
                continue                                   # 버려지지 않음
            rec: dict[str, Any] = {"frame": i, "t": r.get("t"), "conf": float(d.get("conf", 0)),
                                   "bbox": box, "h": round(box[3] - box[1], 4),
                                   "w": round(box[2] - box[0], 4),
                                   "cx": round(_center(box)[0], 3), "cy": round(_center(box)[1], 3)}
            # 앞(t-1, t-2): tid 를 받은 적이 있었나
            prev_tid = None
            prev_det = False
            for k in range(1, WINDOW + 1):
                j = i - k
                if j < 0:
                    break
                pr = rows[j]
                if any(same_person(box, x.get("bbox") or [0, 0, 0, 0]) for x in persons(pr, "fresh")):
                    prev_det = True
                for t in persons(pr, "tracks"):
                    if same_person(box, t.get("bbox") or [0, 0, 0, 0]):
                        prev_tid = prev_tid if prev_tid is not None else int(t.get("tid", -1))
                        break
            # 뒤(t+1, t+2): 검출이 있나 / tid 를 받나
            next_det = False
            next_tid = None
            for k in range(1, WINDOW + 1):
                j = i + k
                if j >= len(rows):
                    break
                nr = rows[j]
                if any(same_person(box, x.get("bbox") or [0, 0, 0, 0]) for x in persons(nr, "fresh")):
                    next_det = True
                for t in persons(nr, "tracks"):
                    if same_person(box, t.get("bbox") or [0, 0, 0, 0]):
                        next_tid = next_tid if next_tid is not None else int(t.get("tid", -1))
                        break
            rec.update({"prev_det": prev_det, "prev_tid": prev_tid,
                        "next_det": next_det, "next_tid": next_tid})
            if prev_tid is not None:
                rec["class"] = "D 트랙 종료"
            elif next_tid is not None:
                rec["class"] = "A 확정 지연"
            elif not next_det and not prev_det:
                rec["class"] = "B 검출 깜빡임"
            elif next_det:
                rec["class"] = "C 반복 탈락"
            else:
                rec["class"] = "E 기타"
                rec["why"] = "앞에만 검출 있고 뒤에는 없음(퇴장 추정)"
            out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="현장 2fps 데이터의 추적 탈락 원인 분류")
    ap.add_argument("--data", default="runs/field_20260827/track_debug.jsonl")
    ap.add_argument("--tau", type=float, default=0.5, help="R-2 분류 기준 τ")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    f = _ROOT / a.data
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    span_s = (rows[-1]["t"] - rows[0]["t"]) / 1000.0
    fps = len(rows) / max(span_s, 1e-9)
    algos = sorted({r.get("algo") for r in rows if r.get("algo")})
    print(f"입력: {a.data}\n  프레임 {len(rows)} · {span_s/60:.1f}분 · {fps:.2f} fps · 추적기 {algos}")

    # ── R-1: τ 스윕 ──────────────────────────────────────────────────────────
    sweeps = [sweep(rows, t) for t in TAUS]
    print(f"\n[R-1] τ 스윕 (버림 정의: fresh person conf>=τ 중 tracks 와 IoU<{TRACK_IOU})")
    print(f"  {'τ':>5} {'추적전':>7} {'버림':>6} {'비율':>7} {'구간':>5} {'2f+':>5} {'2f+%':>7} {'3f+':>5}")
    for s in sweeps:
        print(f"  {s['tau']:>5} {s['n_fresh_person']:>7} {s['n_dropped']:>6} {s['drop_pct']:>6}% "
              f"{s['runs_total']:>5} {s['runs_ge2']:>5} {s['runs_ge2_pct']:>6}% {s['runs_ge3']:>5}")
    need = max(2, int(round(1.0 * fps)) + 1)
    print(f"  ※디바운스 확정(enter_s 1.0s) = {fps:.2f}fps 에서 약 {need}프레임 연속 필요")

    # ── R-2: 분류 ────────────────────────────────────────────────────────────
    items = classify(rows, a.tau)
    cnt = Counter(it["class"] for it in items)
    tot = len(items)
    print(f"\n[R-2] τ={a.tau} 버려진 {tot}건 분류 "
          f"(같은사람 기준 IoU>={SAME_IOU} 또는 중심거리<={SAME_DIST}, 창 t±{WINDOW})")
    for k in sorted(cnt):
        print(f"   {k:14} {cnt[k]:>4}건 ({cnt[k]/max(tot,1)*100:5.1f}%)")
    cd = cnt.get("C 반복 탈락", 0) + cnt.get("D 트랙 종료", 0)
    print(f"   ── C+D(추적기 문제) {cd}건 = {cd/max(tot,1)*100:.1f}%")

    # B 의 크기·위치·conf 분포
    bs = [it for it in items if it["class"].startswith("B")]
    if bs:
        hs = sorted(it["h"] for it in bs)
        cs = sorted(it["conf"] for it in bs)
        cys = sorted(it["cy"] for it in bs)
        print(f"\n   [B 검출 깜빡임 {len(bs)}건] 박스 높이 중앙값 {hs[len(hs)//2]:.3f} "
              f"(최소 {hs[0]:.3f} 최대 {hs[-1]:.3f}) · 화면높이 0.10 미만 "
              f"{sum(1 for h in hs if h < 0.10)}건")
        print(f"      conf 중앙값 {cs[len(cs)//2]:.3f} (최소 {cs[0]:.3f} 최대 {cs[-1]:.3f}) · "
              f"세로중심 중앙값 {cys[len(cys)//2]:.3f}")

    if tot and cd / tot < 0.20:
        print(f"\n★C+D(추적기 문제)가 {cd}/{tot} = {cd/tot*100:.1f}% 로 20% 미만이다.")
    print("\n※이 표는 판정이 아니다 — 결론은 사람이 낸다(규칙 7).")

    if a.json:
        p = _ROOT / a.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "version": VERSION,
            "correction": "v1 의 B 분류 결함 정정 — same_person 중심거리를 고정 0.15 에서 max(0.15, 0.6×max(폭)) 로 바꾸고, 클리핑 박스(h>=0.95)는 가로 중심거리만 본다. v1(audit/passthru_field_20260922.json)은 수정하지 않고 보존한다.",
            "generated": "2026-09-22", "data": a.data,
            "frames": len(rows), "span_min": round(span_s / 60, 1), "fps": round(fps, 2),
            "algo": algos, "declared_criteria": DECLARED_CRITERIA,
            "params": {"TRACK_IOU": TRACK_IOU, "SAME_IOU": SAME_IOU, "SAME_DIST": SAME_DIST,
                       "WINDOW": WINDOW, "CLIP_H": CLIP_H,
                       "same_person_rule": "IoU>=0.30 OR dist<=max(0.15, 0.6*max(w)); h>=0.95 면 가로거리만"},
            "r1_sweep": sweeps, "r2_tau": a.tau,
            "r2_counts": dict(cnt), "r2_items": items,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
