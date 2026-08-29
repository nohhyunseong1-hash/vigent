#!/usr/bin/env python3
"""[③ 판정] ppe_missing 히스테리시스 N 을 훑어 미탐↔오탐 교환비를 잰다.

★원본 영상이 없어도 되는 유일한 판정이다 — 프레임마다 "미착용 상태인가"만 필요하고
박스 정확도는 필요 없다. 판정 기준은 docs/labeling_plan.md §5 에 **측정 전에** 선언했다.

정답 기준은 **장면 대본**이다(프레임 단위 라벨이 아니다 — 한계는 audit 문서 참조).
사용: python benchmarks/hysteresis_sweep.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REQ = {"NO-Hardhat", "NO-Safety-Vest"}          # 학원 프로파일 적용값
TRUE_MISS = {"03_안전모운전", "05_보호구미착용운전", "06_미착용_위험구역",
             "06b_미착용_위험구역_재시도", "06c_미착용_위험구역_3차"}
TRUE_WORN = {"04_안전모조끼운전", "07_착용_위험구역"}   # v1.2 §4-4 '보호구를 갖춰 입은 장면'


def hyst(raws: list[bool], n: int) -> list[bool]:
    """guard._hysteresis 와 같은 규칙 — 연속 n프레임 참이어야 발화, 거짓이면 즉시 리셋."""
    st, out = 0, []
    for r in raws:
        st = min(st + 1, n) if r else 0
        out.append(st >= n)
    return out


def events(b: list[bool]) -> int:
    """연속 True 구간 수 = '건'."""
    return sum(1 for i, x in enumerate(b) if x and (i == 0 or not b[i - 1]))


def main() -> int:
    scenes: dict[str, list[bool]] = {}
    for f in sorted(glob.glob("runs/field_20260827/*/dets.jsonl")):
        s = os.path.basename(os.path.dirname(f))
        rows = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
        scenes[s] = [any(d["class"] in REQ for d in r["detections"]) for r in rows]
    if not scenes:
        print("❌ 원자료 없음: runs/field_20260827/*/dets.jsonl")
        return 1

    print(f"{'N':>2} │ {'정탐 건':>7}{'오탐 건':>8} │ {'정탐 프레임':>11}{'오탐 프레임':>11}")
    res = {}
    for n in (1, 2, 3, 4):
        te = sum(events(hyst(v, n)) for s, v in scenes.items() if s in TRUE_MISS)
        fe = sum(events(hyst(v, n)) for s, v in scenes.items() if s in TRUE_WORN)
        tf = sum(sum(hyst(v, n)) for s, v in scenes.items() if s in TRUE_MISS)
        ff = sum(sum(hyst(v, n)) for s, v in scenes.items() if s in TRUE_WORN)
        res[n] = (te, fe)
        print(f"{n:>2} │ {te:>7}{fe:>8} │ {tf:>11}{ff:>11}")

    te3, fe3 = res[3]
    print("\n★선언한 기준: 미탐 감소 ≥ 오탐 증가면 완화 · 오탐 2배 이상이면 무조건 3 유지")
    for n in (2, 1):
        te, fe = res[n]
        dm, df = te - te3, fe - fe3
        ratio = fe / fe3 if fe3 else float("inf")
        v = ("⛔ 무조건 3 유지(오탐 2배 이상)" if ratio >= 2.0
             else ("✅ 완화 가능" if dm >= df else "3 유지 — 오탐 증가가 더 크다"))
        print(f"  3→{n}: 정탐 건 {dm:+} · 오탐 건 {df:+} (오탐 {ratio:.2f}배) → {v}")
    print("\n★한계: 정답이 장면 대본 수준이다. 02_지게차탑승은 대본이 불명확해 제외했다.")
    print("   위 건수는 판정 단계의 수이며, 실제 알림은 쿨다운·통보 게이트를 더 거친다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
