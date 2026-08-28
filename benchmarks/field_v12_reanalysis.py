#!/usr/bin/env python3
"""[v1.2] 현장 보고서 재분석 — 2026-08-27 원자료만 쓴다(새 촬영 없음).

산출:
  --part A   운전자 제외 on/off 반사실 재현 → "지면 오인이 근접경보 누락을 냈는가"
  --part B   지면 오인 비율(분모 포함) + 95% 신뢰구간
  --part C4  방문 측정 목적 판정 D1(분당 신규 tid) · D5(추적 생존율)

★A 의 핵심: 장면별로 따로 돌리면 디바운서 상태가 초기화돼 결과가 달라진다.
  **전 장면을 시간순 하나로 이어** 운영과 동일한 사슬을 재현해야 한다.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import proximity  # noqa: E402
import zone_debounce  # noqa: E402

KST = timezone(timedelta(hours=9))
FIELD = _ROOT / "runs" / "field_20260827"
AR = 720 / 1280            # C200 stream1 세로/가로 — 세로거리 과대추정 보정(감사 E-1)
ENTER, EXIT, COOL = 0.4, 1.0, 15.0      # 근접 디바운스·쿨다운(운영값)
GROUND_DY = 0.10           # 발끝이 장비 박스 하단보다 이만큼 아래면 '지면'(v1.1 기준 계승)


def _ts(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%H:%M:%S")


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.959964
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    hw = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - hw) * 100, min(1.0, c + hw) * 100)


def _containment(p: list, v: list) -> float:
    ix = max(0.0, min(p[2], v[2]) - max(p[0], v[0]))
    iy = max(0.0, min(p[3], v[3]) - max(p[1], v[1]))
    pa = (p[2] - p[0]) * (p[3] - p[1])
    return (ix * iy / pa) if pa > 0 else 0.0


def _load_all() -> list[dict]:
    """전 장면을 시간순 하나로 잇는다(운영 상태 연속성 재현)."""
    rows: list[dict] = []
    for f in sorted(glob.glob(str(FIELD / "*" / "dets.jsonl"))):
        scene = Path(f).parent.name
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["_scene"] = scene
                rows.append(r)
    rows.sort(key=lambda r: r["t"])
    return rows


def _dets(r: dict) -> list[dict]:
    return [{"class": d.get("class"), "bbox": d.get("bbox")} for d in r.get("detections", [])]


def _has_ground_mis(dets: list[dict]) -> bool:
    """이 프레임에 '지면에 선 사람이 운전자로 오인된' 경우가 있는가."""
    thr = proximity.driver_containment()
    persons = [d for d in dets if d["class"] == "person"]
    vehicles = [d for d in dets if d["class"] in proximity.VEHICLE_REF_M]
    for p in persons:
        for v in vehicles:
            if _containment(p["bbox"], v["bbox"]) >= thr and p["bbox"][3] - v["bbox"][3] >= GROUND_DY:
                return True
    return False


def _replay(rows: list[dict], exclude_driver: bool) -> list[tuple[float, str, bool]]:
    """운영과 동일한 사슬(proximity → 디바운스 → 쿨다운)로 근접경보 시각을 뽑는다."""
    db = zone_debounce.ZoneDebouncer(enter=ENTER, exit_=EXIT)
    cd = -1e9
    fires: list[tuple[float, str, bool]] = []
    clock = {"t": 0.0}
    with mock.patch.object(zone_debounce.time, "time", lambda: clock["t"]):
        for r in rows:
            clock["t"] = t = r["t"] / 1000.0
            dets = _dets(r)
            if exclude_driver:
                hz = proximity.detect(dets, aspect_hw=AR)
            else:   # 반사실: 운전자 제외를 끈다(임계를 1.0 초과로 두면 비활성)
                with mock.patch.object(proximity, "driver_containment", lambda: 1.01):
                    hz = proximity.detect(dets, aspect_hw=AR)
            was = db.state("c")["confirmed"]
            now = db.update("c", bool(hz))
            if now and not was and t - cd >= COOL:
                cd = t
                fires.append((t, r["_scene"], _has_ground_mis(dets)))
    return fires


def part_a(rows: list[dict]) -> None:
    print("\n■ A. 지면 오인이 실제 근접경보 누락을 냈는가 — 반사실 재현")
    print(f"  전 장면 시간순 연결: {len(rows)}프레임 · {_ts(rows[0]['t'])}~{_ts(rows[-1]['t'])}")
    on, off = _replay(rows, True), _replay(rows, False)
    real = [r for r in rows if any("proximity" in str(x) for x in (r.get("fired") or []))]
    print(f"\n  실제 기록 {len(real)}건 · 재현(제외 ON) {len(on)}건 · 재현(제외 OFF) {len(off)}건")
    print("  ⚠재현이 실제와 다르면(장면 사이 미녹화·재시작) 결론은 **재현 기준**이다.")

    extra = [e for e in off if all(abs(e[0] - o[0]) > 2.0 for o in on)]
    print(f"\n  ★운전자 제외가 막은 경보 {len(extra)}건 — 각각 진짜 위험이었나:")
    for t, s, ground in extra:
        tag = "★지면 사람(진짜 위험)" if ground else "실제 탑승자(오경보였을 것)"
        print(f"    {_ts(t * 1000)} [{s}] {tag}")
    lost = [e for e in extra if e[2]]
    print(f"\n  ★★결론: 막힌 경보 {len(extra)}건 중 **진짜 위험 {len(lost)}건**")
    print("     → 0 이면 '누락 없음'(재현 기준), 1 이상이면 '누락 확인'")


def part_b(rows: list[dict]) -> None:
    print("\n■ B-1. 지면 오인 비율 — 분모 포함")
    thr = proximity.driver_containment()
    den = num = 0
    for r in rows:
        dets = _dets(r)
        persons = [d for d in dets if d["class"] == "person"]
        vehicles = [d for d in dets if d["class"] in proximity.VEHICLE_REF_M]
        d_hit = n_hit = False
        for p in persons:
            for v in vehicles:
                if _containment(p["bbox"], v["bbox"]) >= thr:
                    d_hit = True
                    if p["bbox"][3] - v["bbox"][3] >= GROUND_DY:
                        n_hit = True
        den += d_hit
        num += n_hit
    lo, hi = _wilson(num, den)
    print(f"  포함률 {thr} 이상 프레임(분모) = {den}")
    print(f"  그중 지면-오인(발끝차 ≥{GROUND_DY}) = {num}")
    print(f"  ★비율 = **{num / max(den, 1) * 100:.1f}%**  [95% CI {lo:.1f}, {hi:.1f}]")
    print("  (v1.1: 육안 10/210 = 4.8% · 자동 7.6%)")


def part_c4() -> None:
    print("\n■ C-4. 방문 측정 목적 판정 — D1 · D5")
    f = FIELD / "track_debug.jsonl"
    if not f.exists():
        print(f"  데이터 없음: {f}")
        return
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    mins = (rows[-1]["t"] - rows[0]["t"]) / 1000.0 / 60.0
    print(f"  표본 {len(rows)}프레임 · {mins:.1f}분 · {len(rows) / (mins * 60):.2f} fps")
    print(f"  algo 필드(수정 후 코드 증거): {rows[0].get('algo')}")

    tids: set = set()
    pre = post = 0
    for r in rows:
        for t in (r.get("tracks") or []):
            if str(t.get("label", "")).lower() == "person":
                post += 1
                if t.get("tid") is not None:
                    tids.add(t["tid"])
        for d in (r.get("fresh") or []):
            if str(d.get("label", "")).lower() == "person":
                pre += 1

    rate = len(tids) / max(mins, 1e-9)
    d1 = "B 승격" if rate <= 2.0 else ("C 유지 + 완화 검토" if rate <= 5.0 else "C 유지 확정")
    print(f"\n  D1  고유 person tid {len(tids)}개 / {mins:.1f}분 = 분당 {rate:.2f}개")
    print(f"      기준 ≤2.0 / 2.0~5.0 / >5.0 → ★판정: **{d1}**")

    sur = post / max(pre, 1) * 100
    d5 = ("bytetrack 유지 확정" if sur >= 85 else
          "유지 + 검출 보강" if sur >= 75 else "iou 복귀 정식 검토")
    print(f"\n  D5  추적 전 {pre} → 후 {post} = 생존율 {sur:.1f}%")
    print(f"      기준 ≥85 / 75~85 / <75 → ★판정: **{d5}**")
    print("      (참고 dev 1fps 67.4% · 실영상 2fps 73.9%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True, choices=["A", "B", "C4", "all"])
    args = ap.parse_args()
    if not FIELD.exists():
        print(f"원자료 없음: {FIELD}")
        return 2
    if args.part in ("A", "B", "all"):
        rows = _load_all()
    if args.part in ("A", "all"):
        part_a(rows)
    if args.part in ("B", "all"):
        part_b(rows)
    if args.part in ("C4", "all"):
        part_c4()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
