"""benchmarks/local_slowdown_ab.py — Phase 2: safety-local extrapCap 0.6→0.85 A/B (표시오차·정지프레임·
오버슈트, 실배포 캐던스 재현). 수정은 코드 1줄(index_local.html `_bt` extrapCap) — 이 스크립트는 그
전/후를 실측 재생으로 검증한다.

판정 기준(사용자 지시): 정지프레임은 개선 확인됨(Phase 1). 오버슈트(방향전환 역오차)가 크게 늘면
0.85 대신 0.75 로 물러선다 — 그래서 0.6/0.75/0.85 세 값을 함께 잰다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import box_quality as bq  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CADENCES = (100, 150)
VARIANTS: dict[str, dict[str, Any]] = {
    "0.6(수정 전)": {"extrapCap": 0.6},
    "0.75(대안)": {"extrapCap": 0.75},
    "0.85(채택, hub와 동일)": {"extrapCap": 0.85},
}


def _fmt(b: dict[str, Any]) -> str:
    return f"{b['p50']:.1f}/{b['p95']:.1f}" if b["p50"] is not None else "—"


def main() -> None:
    frames, _fps = bq.load_detections_cache(_HERE / "_sweep_cache" / "multi_scene.json")
    thresholds = bq.global_speed_thresholds(frames)

    lines = [
        "# Phase 2 — safety-local extrapCap 0.6→0.85 A/B (person 실측, multi_scene.mp4)",
        "",
        "실배포 폴링 캐던스(100/150ms) 재현 + 5개 지연 시나리오 전부. 판정: 정지프레임 개선 유지되는지, "
        "오버슈트(방향전환 역오차)가 크게 늘지 않는지, person 표시오차 악화 없는지.",
        "",
    ]

    summary_rows = []
    for cadence in CADENCES:
        ingest_frames = bq.subsample_for_ingest(frames, cadence)
        lines.append(f"## ingest 캐던스 {cadence}ms ({len(frames)}프레임 → {len(ingest_frames)}개 갱신)")
        for sc in bq.SCENARIOS:
            lines.append(f"### {sc['label']}")
            lines.append("| extrapCap | 느림p50/p95 | 중간p50/p95 | 빠름p50/p95 | 정지% | 겹침% | 오버슈트p50/p95(n) |")
            lines.append("|---|---|---|---|---|---|---|")
            for name, opts in VARIANTS.items():
                vis = bq.run_display_scenario(ingest_frames, sc, "node", None, 12345, opts)
                m = bq.compute_metrics(frames, vis, thresholds)
                b = m["buckets"]
                ov50 = m.get("overshoot_p50")
                ov95 = m.get("overshoot_p95")
                ovn = m.get("overshoot_n", 0)
                ov_txt = f"{ov50:.1f}/{ov95:.1f}({ovn})" if ov50 is not None else f"—({ovn})"
                lines.append(f"| {name} | {_fmt(b['느림'])} | {_fmt(b['중간'])} | {_fmt(b['빠름'])} "
                             f"| {m['freeze_pct']:.1f} | {m['overlap_pct']:.1f} | {ov_txt} |")
                if sc["name"] == "mac_real":
                    summary_rows.append((cadence, name, m["freeze_pct"], ov50, ov95, ovn))
            lines.append("")

    lines += ["## 요약(맥 실사용 시나리오만, 판정 근거)", "",
              "| 캐던스 | extrapCap | 정지% | 오버슈트p50/p95(n) |", "|---|---|---|---|"]
    for cadence, name, freeze, ov50, ov95, ovn in summary_rows:
        ov_txt = f"{ov50:.1f}/{ov95:.1f}({ovn})" if ov50 is not None else f"—({ovn})"
        lines.append(f"| {cadence}ms | {name} | {freeze:.1f} | {ov_txt} |")

    lines += [
        "",
        "## person 회귀 확인",
        "위 표의 'person 표시오차(느림/중간/빠름 p50·p95)'가 곧 person 지표다(이 클립엔 실측 person만 "
        "있음, PPE는 이전 A/B에서 합성 신호로 별도 확인 완료 — ppe_anchor_ab.md). 0.6→0.85 사이 표시오차 "
        "변화가 미미한지 위 본문 표에서 직접 대조.",
    ]

    out = _HERE / "local_slowdown_ab.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
