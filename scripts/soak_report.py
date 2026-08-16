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

    rss = [r["rss_mb"] for r in rows if r.get("rss_mb")]
    growth = ((rss[-1] - rss[0]) / dur_h) if (rss and dur_h > 0.1) else 0.0
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
        (f"RSS 증가 ≤{max_growth:.0f}MB/h", abs(growth) <= max_growth, f"{growth:+.1f}MB/h"),
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
    if gpu:
        print(f"  GPU: 시작 {gpu[0]} → 끝 {gpu[-1]} MiB (최대 {max(gpu)})")
    if dur_h < 23.5:
        print(f"\n  ※ 경과 {dur_h:.1f}시간 — 24시간 미달이라 최종 판정이 아니다(중간 점검).")

    print(f"\n종합: {'PASS' if ok_all else 'FAIL'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
