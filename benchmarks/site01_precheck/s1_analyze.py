#!/usr/bin/env python3
"""[S1] 현장 영상 원시 검출 분석 — 크기별 conf · 영상 타임라인 매핑 · 클래스 분포.

raw_samples.json(관찰 시각 t + 검출 목록)을 영상 타임라인(t mod 루프길이)으로 접어,
"영상의 몇 초 구간에서 무엇이 잡히고 안 잡혔는지"를 만든다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "runs/site01_eval/site1/raw_samples.json"   # [C5] 절대경로 제거(JSON 은 저장소에 남음)
# ★파일 카메라는 검출 주기마다 1프레임을 순차로 읽는다(worker.py:919) → 30fps 영상은
#   2fps 페이싱에서 1/15 배속. 영상시각 = 관찰시각 ÷ SPEED.
SPEED = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
PPE_ON = {"Hardhat", "Safety-Vest", "Safety Vest", "Mask"}
PPE_OFF = {"NO-Hardhat", "NO-Safety-Vest", "NO-Safety Vest", "NO-Mask"}
FIRE = {"fire", "smoke", "Fire", "Smoke"}


def main() -> int:
    samples = json.loads(RAW.read_text(encoding="utf-8"))
    print(f"샘플 {len(samples)}개 · 배속 1/{SPEED:.0f} (영상시각 = 관찰 ÷ {SPEED:.0f})")

    # ── 1. 클래스 분포 ──────────────────────────────────────────
    cnt = Counter()
    confs = defaultdict(list)
    for s in samples:
        for d in s["dets"]:
            cnt[d["c"]] += 1
            confs[d["c"]].append(d["f"])
    print("\n[클래스 분포]")
    for c, n in cnt.most_common():
        v = confs[c]
        print(f"  {c:ME18s}".replace("ME", "") if False else f"  {c:18s} {n:5d}건 · conf 평균 {sum(v)/len(v):.3f} · 최소 {min(v):.3f} · 최대 {max(v):.3f}")

    # ── 2. person 크기(박스 높이) 대 conf ───────────────────────
    print("\n[person 크기별 conf] (박스 높이 = 화면 대비 비율)")
    buckets = defaultdict(list)
    for s in samples:
        for d in s["dets"]:
            if d["c"] != "person" or not d.get("b"):
                continue
            hh = d["b"][3] - d["b"][1]
            k = ("<5%" if hh < 0.05 else "5~10%" if hh < 0.10 else "10~20%" if hh < 0.20
                 else "20~40%" if hh < 0.40 else ">=40%")
            buckets[k].append(d["f"])
    for k in ["<5%", "5~10%", "10~20%", "20~40%", ">=40%"]:
        v = buckets.get(k, [])
        if v:
            print(f"  높이 {k:6s}: {len(v):5d}건 · conf 평균 {sum(v)/len(v):.3f} · 최소 {min(v):.3f}")
        else:
            print(f"  높이 {k:6s}: 0건")

    # ── 3. 영상 타임라인(초 구간별) — 조명/장면 변화 탐지용 ─────
    print("\n[영상 타임라인 5초 구간별] (관찰 t 를 루프로 접음 — 여러 루프 평균)")
    tl_pc = defaultdict(list)      # 구간 → person 수 목록
    tl_conf = defaultdict(list)
    for s in samples:
        pos = s["t"] / SPEED
        k = int(pos // 2) * 2
        persons = [d for d in s["dets"] if d["c"] == "person"]
        tl_pc[k].append(len(persons))
        for d in persons:
            tl_conf[k].append(d["f"])
    for k in sorted(tl_pc):
        pcs = tl_pc[k]
        cf = tl_conf.get(k, [])
        print(f"  영상 {k:3d}~{k+2:3d}s: 표본 {len(pcs):3d} · person 평균 {sum(pcs)/len(pcs):.2f}"
              f" (최소 {min(pcs)} 최대 {max(pcs)})"
              + (f" · conf 평균 {sum(cf)/len(cf):.3f}" if cf else " · (person 없음)"))

    # ── 4. person 공백(≥1.5s) → 영상 타임라인 위치 ──────────────
    print("\n[person 공백 구간(관찰시각 → 영상 내 위치)]")
    run = None
    gaps = []
    for s in samples:
        has_p = any(d["c"] == "person" for d in s["dets"])
        if not has_p:
            run = [s["t"], s["t"]] if run is None else [run[0], s["t"]]
        else:
            if run and run[1] - run[0] >= 1.5:
                gaps.append(run)
            run = None
    if run and run[1] - run[0] >= 1.5:
        gaps.append(run)
    if not gaps:
        print("  없음")
    for g in gaps:
        print(f"  관찰 {g[0]:.1f}~{g[1]:.1f}s → 영상 {g[0]/SPEED:.1f}~{g[1]/SPEED:.1f}s (영상 기준 {(g[1]-g[0])/SPEED:.1f}s)")

    # ── 5. 저신뢰 이상 검출(오탐 후보) ─────────────────────────
    print("\n[오탐 후보: conf < 0.45 또는 비일상 클래스]")
    odd = Counter()
    for s in samples:
        for d in s["dets"]:
            if d["f"] < 0.45 or (d["c"] not in {"person"} | PPE_ON | PPE_OFF | FIRE):
                odd[(d["c"], round(d["f"], 1))] += 1
    for (c, f), n in odd.most_common(15):
        print(f"  {c} conf~{f}: {n}건")
    if not odd:
        print("  없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
