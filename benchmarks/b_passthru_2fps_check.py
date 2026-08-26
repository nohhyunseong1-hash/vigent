#!/usr/bin/env python3
"""[B-passthru] 2fps 재측정 — "되살린 검출이 전부 단발인가"를 현장 데이터로 닫는다.

★왜 이 측정이 필요한가(2026-08-25):
  dev(1fps 표본)에서 검출통과가 되살린 박스는 **11구간이 전부 1프레임**이었고,
  디바운스(enter_s=1.0초)를 못 넘어 **경보가 하나도 늘지 않았다**.
  그런데 1fps 표본에서는 "1프레임 = 1초"라 연속성 판단이 극도로 불리하다.
  운영은 **2fps(0.5초 간격)** 이므로 같은 사람이 2~3프레임 연속 잡힐 가능성이 훨씬 높다.
  → **표본의 산물인지 실제 성질인지**를 현장 2fps 데이터로 가른다.

무엇을 재는가:
  `track_debug.jsonl` 은 프레임마다 **추적 전(fresh)** 과 **추적 후(tracks)** 를 함께 남긴다.
  둘을 대조하면 **추적이 버린 person 박스**를 프레임 단위로 특정할 수 있다.
  그 버려진 박스가 **몇 프레임 연속** 나타나는지(구간 길이 분포)가 답이다.

★판정 기준 (미리 선언 — 사후 합리화 방지):
  · 2프레임 이상 구간이 **전체 구간의 30% 이상** → **passthrough 를 그대로 켠다**
    (디바운스를 건드리지 않고도 경보가 살아난다는 뜻)
  · 30% 미만이지만 **0% 는 아님** → 부분 이득. 켜되 경보 증가를 현장에서 재확인
  · **여전히 전부 단발(2프레임 이상 0%)** → 디바운스 완화(②③)를 그때 **재검토**
  · 표본이 **20분 미만**이거나 버려진 박스가 **30건 미만** → "측정 불충분", 현행 유지

사용:
    # 학원에서 VIGENT_TRACK_DEBUG=1 로 20분 이상 수집한 뒤
    python benchmarks/b_passthru_2fps_check.py --data data/track_debug.jsonl
    python benchmarks/b_passthru_2fps_check.py --data ... --conf 0.6   # 검출통과 임계와 맞출 것
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TRACK_IOU = 0.45          # guard.TRACK_IOU — "같은 객체로 볼 겹침" 기준과 맞춘다


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/track_debug.jsonl")
    ap.add_argument("--conf", type=float, default=0.6,
                    help="검출통과 임계 — 이 값 이상만 되살린다(track.passthrough_conf 와 맞출 것)")
    args = ap.parse_args()

    f = _ROOT / args.data
    if not f.exists():
        print(f"데이터 없음: {args.data}")
        return 2
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        print("빈 파일")
        return 2

    span_s = (rows[-1]["t"] - rows[0]["t"]) / 1000.0
    fps = len(rows) / max(span_s, 1e-9)
    print(f"\n입력: {args.data}")
    print(f"  프레임 {len(rows)} · 구간 {span_s / 60:.1f}분 · 평균 {fps:.2f} fps")
    if fps < 1.5:
        print("  ⚠**1fps 급 표본이다** — 이 측정의 목적(2fps 확인)에 맞지 않는다. 참고용으로만 본다.")

    # 프레임마다 '추적이 버린 고신뢰 person' 을 특정한다
    dropped_per_frame: list[bool] = []
    n_dropped = n_fresh = 0
    for r in rows:
        fresh = [d for d in (r.get("fresh") or [])
                 if str(d.get("label", "")).lower() == "person"
                 and float(d.get("conf", 0)) >= args.conf]
        tracks = [t.get("bbox") or [0, 0, 0, 0] for t in (r.get("tracks") or [])
                  if str(t.get("label", "")).lower() == "person"]
        n_fresh += len(fresh)
        drop = [d for d in fresh
                if all(_iou(d.get("bbox") or [0, 0, 0, 0], tb) < TRACK_IOU for tb in tracks)]
        n_dropped += len(drop)
        dropped_per_frame.append(bool(drop))

    # 연속 구간 길이 분포
    runs: list[int] = []
    cur = 0
    for hit in dropped_per_frame:
        if hit:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)

    print(f"\n  추적 전 고신뢰 person(conf≥{args.conf}): {n_fresh}건")
    print(f"  ★그중 추적이 버린 것: **{n_dropped}건** ({n_dropped / max(n_fresh, 1) * 100:.1f}%)")
    if not runs:
        print("\n  버려진 박스가 0건이다 — 이 표본에서는 검출통과가 할 일이 없다.")
        print("  ★확인할 것: 수집 당시 추적기가 **bytetrack** 이었는가?")
        print("    iou 트래커는 검출을 버리지 않는다(오히려 코스팅으로 출력>입력) —")
        print("    iou 로 수집한 데이터로는 이 판정을 할 수 없다(config track.algo 확인).")
        return 0

    dist = Counter(runs)
    ge2 = sum(c for L, c in dist.items() if L >= 2)
    print(f"\n  ★버려진 박스의 **연속 구간 길이 분포** (총 {len(runs)}구간)")
    for L in sorted(dist):
        bar = "█" * min(40, dist[L])
        print(f"    {L:>3}프레임 : {dist[L]:>4}구간  {bar}")
    ratio = ge2 / len(runs) * 100
    print(f"\n  **2프레임 이상 구간: {ge2}/{len(runs)} = {ratio:.1f}%**")
    print(f"  (디바운스 확정 조건 = enter_s 1.0초 → {fps:.1f}fps 에서 약 "
          f"{max(2, int(round(1.0 * fps)) + 1)}프레임 연속)")

    print("\n★판정(미리 선언한 기준)")
    if span_s < 20 * 60 or n_dropped < 30:
        print(f"  ⏸ **측정 불충분** — 표본 {span_s/60:.1f}분(기준 20분) · 버려진 박스 "
              f"{n_dropped}건(기준 30건). **현행 유지**(passthrough off).")
        return 0
    if ratio >= 30.0:
        print("  ✅ **passthrough 를 그대로 켠다** — 2프레임 이상이 30% 이상이다.")
        print("     디바운스를 건드리지 않고도 경보가 살아난다.")
        print("     ★켤 때 체크리스트: benchmarks/b_passthru_results.md §7")
    elif ratio > 0.0:
        print("  🟡 **부분 이득** — 켜되 현장에서 경보 증가를 재확인한다(폰 알림 2배 이내인지).")
    else:
        print("  ❌ **여전히 전부 단발** — 1fps 표본의 산물이 아니라 실제 성질이다.")
        print("     디바운스 완화(검출통과 주체 한정)를 그때 재검토한다.")
        print("     ★단 [B6] 이 막은 '단일 프레임 오검출 = 즉시 경보' 위험을 함께 판단할 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
