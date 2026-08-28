#!/usr/bin/env python3
"""[v1.2 정정] 보호구 경보 중 '마스크 단독' 비율 — **군집 부트스트랩** CI.

★왜 다시 재는가(2026-08-28 지적):
  기존 CI [14.6–21.4] 는 490건을 **독립 시행**으로 둔 이항 신뢰구간이다.
  그러나 판정은 **0.5초 간격 프레임**에서 나온다 — 같은 사람이 같은 자세로 연속 잡힌
  경보는 서로 독립이 아니다. 유효 표본은 490보다 훨씬 작고, 따라서 **이항 CI 는 실제보다
  좁다(과신)**. 군집(장면 / 인물-에피소드) 단위로 다시 뽑아야 정직하다.

두 가지 군집 정의로 각각 낸다:
  · **장면 군집(9개)** — 가장 보수적. 장면이 통째로 뽑히거나 빠진다.
  · **에피소드 군집** — 연속 발화 구간(간격 > gap 초면 끊는다)을 하나로 본다.
    장면보다 잘게 나뉘어 표본이 늘지만, 프레임 독립보다는 여전히 보수적이다.

사용:
    python benchmarks/ppe_mask_share_ci.py
    python benchmarks/ppe_mask_share_ci.py --iters 20000 --gap 3.0

★재실행 조건 — 증거 사진 175장이 확보되면
  현재 입력은 `runs/field_20260827/*/dets.jsonl`(좌표·라벨만, 개인정보 없음)이다.
  경보 증거 사진 175장이 개발 PC 로 오면 **표본이 늘어** 다시 판단할 수 있다:
    1) 사진을 dets 와 시각 매핑(방식: benchmarks/field_v12_reanalysis.py 의 스틸 매핑과 동일)
    2) 각 경보를 육안 분류(마스크 단독 / 실제 미착용 / 오탐)
    3) 이 스크립트를 그대로 재실행 — 입력이 dets 이므로 **코드 수정 없이 동작**한다
    4) 군집 수가 8개(장면)보다 늘면 그때 신뢰구간 인용 여부를 다시 판단한다
  ★현재는 군집 8개뿐이라 **어떤 신뢰구간도 인용하지 않는다**(2026-08-28 결정).
     관측값만 쓴다: "이 표본 490건 중 87건이 마스크 단독 원인이었다."
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from math import sqrt
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

FIELD = _ROOT / "runs" / "field_20260827"
MISS = {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"}


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.959964
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - hw) * 100, min(1.0, c + hw) * 100)


def _collect() -> list[tuple[str, float, bool]]:
    """보호구 경보 1건 = (장면, 시각초, 마스크단독인가)."""
    out = []
    for f in sorted(FIELD.glob("*/dets.jsonl")):
        scene = f.parent.name
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "ppe_missing" not in (r.get("fired") or []):
                continue
            hits = {d["class"] for d in r["detections"] if d["class"] in MISS}
            out.append((scene, r["t"] / 1000.0, hits == {"NO-Mask"}))
    return out


def _episodes(events: list[tuple[str, float, bool]], gap: float) -> list[list[bool]]:
    """연속 발화 구간을 하나의 군집으로 묶는다(장면 안에서 gap 초 이상 끊기면 분리)."""
    by_scene: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for s, t, m in events:
        by_scene[s].append((t, m))
    eps: list[list[bool]] = []
    for s in by_scene:
        rows = sorted(by_scene[s])
        cur = [rows[0][1]]
        for i in range(1, len(rows)):
            if rows[i][0] - rows[i - 1][0] > gap:
                eps.append(cur)
                cur = []
            cur.append(rows[i][1])
        if cur:
            eps.append(cur)
    return eps


def _boot(clusters: list[list[bool]], iters: int, seed: int) -> tuple[float, float]:
    """군집 부트스트랩 — 군집을 복원추출해 비율 분포를 만든다."""
    rng = random.Random(seed)
    n = len(clusters)
    vals = []
    for _ in range(iters):
        pick = [clusters[rng.randrange(n)] for _ in range(n)]
        num = sum(sum(c) for c in pick)
        den = sum(len(c) for c in pick)
        if den:
            vals.append(num / den * 100)
    vals.sort()
    return (vals[int(len(vals) * 0.025)], vals[int(len(vals) * 0.975)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--gap", type=float, default=3.0, help="에피소드를 끊는 무발화 간격(초)")
    ap.add_argument("--seed", type=int, default=20260828)
    args = ap.parse_args()

    ev = _collect()
    if not ev:
        print("데이터 없음")
        return 2
    n, k = len(ev), sum(1 for e in ev if e[2])
    print(f"\n보호구 경보 {n}건 · 그중 마스크 단독 {k}건 = {k / n * 100:.1f}%")

    lo, hi = _wilson(k, n)
    print(f"\n① 이항 CI(기존, **프레임을 독립으로 가정**)      [{lo:.1f}, {hi:.1f}]")
    print("   ⚠0.5초 간격 프레임은 독립이 아니다 — 이 구간은 실제보다 좁다(과신).")

    # 장면 군집
    by_scene: dict[str, list[bool]] = defaultdict(list)
    for s, _t, m in ev:
        by_scene[s].append(m)
    sc = list(by_scene.values())
    slo, shi = _boot(sc, args.iters, args.seed)
    print(f"\n② 장면 군집 부트스트랩({len(sc)}개 장면)          [{slo:.1f}, {shi:.1f}]")
    print("   가장 보수적 — 장면이 통째로 뽑히거나 빠진다.")

    eps = _episodes(ev, args.gap)
    elo, ehi = _boot(eps, args.iters, args.seed)
    print(f"\n③ 에피소드 군집 부트스트랩({len(eps)}개, gap {args.gap}s) [{elo:.1f}, {ehi:.1f}]")

    print("\n★장면 유형별 — '마스크 제외'로 줄어드는 경보")
    print(f"  {'장면':<26}{'보호구 경보':>10}{'마스크 단독':>11}{'감소율':>9}")
    for s in sorted(by_scene):
        v = by_scene[s]
        print(f"  {s:<26}{len(v):>10}{sum(v):>11}{sum(v) / len(v) * 100:>8.1f}%")
    hot = {s for s in by_scene if s.startswith(("04", "07"))}
    hk = sum(sum(by_scene[s]) for s in hot)
    hn = sum(len(by_scene[s]) for s in hot)
    ok_ = k - hk
    on_ = n - hn
    print(f"\n  04·07(완전/부분 착용 장면) {hn:>4}건 중 {hk:>3}건 = {hk / hn * 100:.1f}%")
    print(f"  그 외 장면              {on_:>4}건 중 {ok_:>3}건 = {ok_ / on_ * 100:.1f}%")
    print("\n★해석: 감소폭은 **운영에서 '보호구를 갖춰 입은 사람이 화면에 오래 머무는' 비중**에")
    print("   비례한다. 이 표본의 17.8% 를 운영 전체에 그대로 적용하면 과장이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
