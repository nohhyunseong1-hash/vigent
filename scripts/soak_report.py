#!/usr/bin/env python3
"""[S0] 소크 결과 분석 — soak_realcam.py 가 남긴 JSONL → 합격/불합격 표.

사용:  python scripts/soak_report.py audit/soak_realcam_2026-08-17_0230.jsonl

판정은 기록 파일 머리(header.pass_criteria)에 **소크 시작 전에 선언한 기준**으로 한다
(사후에 기준을 맞추지 않기 위해 — 규칙7).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(p: Path) -> tuple[dict, list[dict]]:
    header: dict = {}
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("_type") == "header":
            header = d
        else:
            rows.append(d)
    return header, rows


def main() -> int:
    if len(sys.argv) < 2:
        print("사용: python scripts/soak_report.py <soak_realcam_*.jsonl>")
        return 2
    p = Path(sys.argv[1])
    if not p.exists():
        print(f"파일 없음: {p}")
        return 2
    header, rows = load(p)
    if not rows:
        print("샘플이 없습니다(소크가 아직 시작 단계일 수 있습니다).")
        return 1

    crit = header.get("pass_criteria", {})
    iv = float(header.get("interval_s") or 60)
    dur_h = rows[-1]["t"] / 3600 if rows else 0

    unhealthy = [r for r in rows if r.get("status") == "unhealthy"]
    degraded = [r for r in rows if r.get("status") == "degraded"]
    noresp = [r for r in rows if r.get("code") == 0]
    degraded_min = len(degraded) * iv / 60

    # 자동복구 실패: stale 상태가 연속으로 (60초 초과) 이어진 뒤에도 회복 안 된 구간
    stale_runs, cur = [], 0
    for r in rows:
        bad = any((c.get("s") or "") in ("stale_detect", "stale_frame")
                  for c in (r.get("cams") or {}).values())
        if bad:
            cur += 1
        elif cur:
            stale_runs.append(cur)
            cur = 0
    if cur:
        stale_runs.append(cur)
    unrecovered = 1 if cur else 0          # 끝까지 회복 못 한 구간
    longest_stale_min = (max(stale_runs) * iv / 60) if stale_runs else 0

    # RSS 증가율 — [R4, 2026-08-18] 판정 로직 2건 수정
    #   ① **감소는 실패가 아니다**: 이전엔 abs(기울기)로 비교해 -163.9MB/h 가 FAIL 로 나왔다.
    #      메모리가 줄어드는 것은 누수의 반대다. 양의 기울기만 상한과 비교한다.
    #   ② **계단식 낙차 분리**: 외부 요인(GPU 부하로 인한 Windows 워킹셋 트리밍 등)으로 RSS 가
    #      한 샘플에 수백MB 급락하면 전체 단일 회귀가 무의미해진다(실측: 구간별 +1.2 ~ -4.9MB/h
    #      인데 전체로는 -163.9MB/h). 큰 스텝을 경계로 구간을 나눠 구간별 기울기를 내고,
    #      **판정은 최악(가장 큰 양의 기울기) 구간**으로 한다 — 누수를 놓치지 않기 위해.
    MIN_HOURS_FOR_GROWTH = 2.0
    STEP_MB = 300.0          # 한 샘플에 이만큼 변하면 외부 요인에 의한 계단으로 본다
    MIN_SEG_SAMPLES = 10
    rss_pts = [(r["t"] / 3600.0, r["rss_mb"]) for r in rows if r.get("rss_mb")]
    rss = [v for _, v in rss_pts]

    def _slope(pts):
        n = len(pts)
        if n < MIN_SEG_SAMPLES:
            return None
        mx = sum(x for x, _ in pts) / n
        my = sum(y for _, y in pts) / n
        den = sum((x - mx) ** 2 for x, _ in pts)
        return (sum((x - mx) * (y - my) for x, y in pts) / den) if den else 0.0

    # 계단 경계로 구간 분할
    segs, cur = [], []
    for i, pt in enumerate(rss_pts):
        if i and abs(pt[1] - rss_pts[i - 1][1]) >= STEP_MB:
            segs.append(cur)
            cur = []
        cur.append(pt)
    segs.append(cur)
    segs = [sg for sg in segs if len(sg) >= MIN_SEG_SAMPLES]
    steps = len(segs) - 1 if len(segs) > 1 else 0

    growth: float | None = None
    seg_slopes: list[tuple[float, float, float]] = []      # (기울기, 시작h, 길이h)
    if rss_pts and dur_h >= MIN_HOURS_FOR_GROWTH:
        for sg in segs:
            sl = _slope(sg)
            if sl is not None:
                seg_slopes.append((sl, sg[0][0], sg[-1][0] - sg[0][0]))
        if seg_slopes:
            growth = max(s for s, _, _ in seg_slopes)      # 최악(가장 큰 양의 기울기) 구간
    gpu = [r["gpu_mb"] for r in rows if r.get("gpu_mb")]
    pend_end = (rows[-1].get("alerts") or {}).get("pending", 0)
    rc_end = max([c.get("rc") or 0 for r in rows for c in (r.get("cams") or {}).values()] or [0])

    print(f"소크 기록: {p.name}")
    print(f"  시작 {header.get('started_at')} / 종료예정 {header.get('ends_at')}")
    print(f"  샘플 {len(rows)}개 · 경과 {dur_h:.1f}시간 (간격 {iv:.0f}초)\n")

    max_deg = float(crit.get("degraded_minutes_max", 5))
    max_growth = float(crit.get("rss_growth_mb_per_hour_max", 30))
    checks = [
        ("unhealthy 0회", len(unhealthy) == 0, f"{len(unhealthy)}회"),
        (f"degraded 누적 ≤{max_deg:.0f}분", degraded_min <= max_deg, f"{degraded_min:.1f}분"),
        ("자동복구 실패 0", unrecovered == 0,
         f"미회복 {unrecovered} (최장 stale {longest_stale_min:.1f}분)"),
        # ★감소(음수)는 통과 — 누수의 반대다. 상한과 비교하는 것은 '증가'뿐이다.
        (f"RSS 증가 ≤{max_growth:.0f}MB/h",
         True if growth is None else growth <= max_growth,
         "판정보류(구간 <2h)" if growth is None
         else (f"{growth:+.1f}MB/h" + (f" (최악 구간, 계단 {steps}회 분리)" if steps else ""))),
        ("미전송 경보 0건", int(pend_end or 0) == 0, f"{pend_end}건"),
    ]
    print(f"{'기준':<28} {'결과':<24} 판정")
    print("-" * 62)
    ok_all = True
    for name, ok, got in checks:
        ok_all &= ok
        print(f"{name:<28} {got:<24} {'PASS' if ok else 'FAIL'}")

    print("\n부가 관측")
    print(f"  서버 무응답(HTTP 0) 샘플: {len(noresp)}개")
    print(f"  재연결 누적: {rc_end}회")
    if rss:
        print(f"  RSS: 시작 {rss[0]:.0f} → 끝 {rss[-1]:.0f} MB (최대 {max(rss):.0f})")
    if steps:
        print(f"  ※ RSS 계단 낙차 {steps}회 감지(±{STEP_MB:.0f}MB 이상) — 외부 요인 가능성."
              f" 구간별 기울기로 판정했다:")
        for sl, st_h, ln in seg_slopes:
            print(f"     t={st_h:5.1f}h ~ {st_h + ln:5.1f}h ({ln:4.1f}h)  {sl:+7.2f} MB/h")
    if gpu:
        print(f"  GPU: 시작 {gpu[0]} → 끝 {gpu[-1]} MiB (최대 {max(gpu)})")
    if dur_h < 23.5:
        print(f"\n  ※ 경과 {dur_h:.1f}시간 — 24시간 미달이라 최종 판정이 아니다(중간 점검).")

    print(f"\n종합: {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
