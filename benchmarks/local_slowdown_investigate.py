"""benchmarks/local_slowdown_investigate.py — Phase 1: safety-local "앵커 제거 후 느려짐" 원인 분해
(측정 전용, 코드 무수정).

배경: PPE 앵커 제거(커밋 e4331bd) 후 person/PPE 박스가 반 박자 느려진 느낌이 있다는 보고.
앵커를 되살리는 건 금지(끌림 재발) — 대신 (a) 검출 갱신주기 저하 vs (b) 보간(extrapCap 등)
파라미터 미흡 중 무엇이 지배적인지 실측으로 가른다.

이 스크립트는 (b)만 다룬다 — extrapCap 0.6(현재 기본, index_local.html `_bt`) vs 0.85(index_hub.html
`_spotBt` 값)을 box_quality.py 의 실측 재생 하네스로 비교한다. **핵심**: box_quality.py 의 기본
시나리오는 원본 캐시의 조밀한 프레임(24fps≈42ms)을 그대로 ingest 하는데, 이는 실배포 폴링 간격
(DETECT_MIN_INTERVAL_MS=100ms, realtime_core.js:175)보다 2배 이상 촘촘해 extrapCap 차이가 거의
안 드러난다 — `subsample_for_ingest(frames, 100)`로 실배포 캐던스를 재현해야 차이가 보인다(이 스크립트가
그렇게 함).

(a) 검출 갱신주기 저하(실측 RTT·서버 경합)는 라이브 서버+워커가 필요해 별도로(대화형으로) 측정했고
결과는 이 스크립트가 아니라 커밋 메시지/보고에 직접 남긴다(재현 시 서버 기동 후 /detect/frame 반복
호출 + POST /cameras 로 워커 동시 기동해 RTT 비교하면 됨).

실행: python3 benchmarks/local_slowdown_investigate.py
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

CADENCES = (0, 100, 150)   # 0=원본 조밀(대조군, 캐던스 효과 없음 확인용) · 100/150=실배포 근사
VARIANTS: dict[str, dict[str, Any]] = {
    "현재(extrapCap 0.6=기본)": {},
    "hub식(extrapCap 0.85)": {"extrapCap": 0.85},
}
SCENARIO_NAMES = ("ideal", "mac_real")   # 지연0(대조군) vs 맥 실사용 지연+지터(실조건)


def _fmt(b: dict[str, Any]) -> str:
    return f"{b['p50']:.1f}/{b['p95']:.1f}" if b["p50"] is not None else "—"


def main() -> None:
    frames, _fps = bq.load_detections_cache(_HERE / "_sweep_cache" / "multi_scene.json")
    thresholds = bq.global_speed_thresholds(frames)

    lines = [
        "# Phase 1 — safety-local 느려짐 원인분해: (b) 보간(extrapCap) 실측 (측정 전용)",
        "",
        "person 실측(multi_scene.mp4, 497프레임) 기준. extrapCap 0.6(현재)과 0.85(index_hub.html "
        "`_spotBt` 값)를 ingest 캐던스별로 비교 — 0ms(원본 조밀, 대조군)와 100/150ms(실배포 폴링 간격 "
        "근사, `subsample_for_ingest`)에서 차이가 어떻게 벌어지는지 본다.",
        "",
    ]

    for cadence in CADENCES:
        ingest_frames = bq.subsample_for_ingest(frames, cadence) if cadence else frames
        lines.append(f"## ingest 캐던스 {cadence}ms ({len(frames)}프레임 → {len(ingest_frames)}개 갱신)")
        for sc in bq.SCENARIOS:
            if sc["name"] not in SCENARIO_NAMES:
                continue
            lines.append(f"### {sc['label']}")
            lines.append("| 설정 | 느림p50/p95 | 중간p50/p95 | 빠름p50/p95 | 정지% | 겹침% |")
            lines.append("|---|---|---|---|---|---|")
            for name, opts in VARIANTS.items():
                vis = bq.run_display_scenario(ingest_frames, sc, "node", None, 12345, opts)
                m = bq.compute_metrics(frames, vis, thresholds)
                b = m["buckets"]
                lines.append(f"| {name} | {_fmt(b['느림'])} | {_fmt(b['중간'])} | {_fmt(b['빠름'])} "
                             f"| {m['freeze_pct']:.1f} | {m['overlap_pct']:.1f} |")
            lines.append("")

    lines += [
        "## 해석",
        "- **원본 조밀 캐던스(0ms)에서는 extrapCap 0.6→0.85 차이가 거의 없다** — 이 조건에서 갱신 간격이",
        "  이미 촘촘해(≈42ms) extrapCap 상한(0.6×42≈25ms, 0.85×42≈36ms 소요)에 걸릴 일이 드물다.",
        "- **실배포 캐던스(100/150ms) + 맥 실사용 지연·지터에서는 정지프레임%가 눈에 띄게 벌어진다**",
        "  (본문 표 참고) — 표시오차(px)는 거의 동일하거나 미세하게만 나빠지는데 정지프레임은 뚜렷이",
        "  준다 — extrapCap 상향이 '거의 공짜'인 트레이드오프로 보인다(실측, 이 클립 한정).",
        "",
        "## (a) 검출 갱신주기·서버 경합 — 별도 라이브 측정(이 스크립트 범위 밖, 결과만 기록)",
        "- `/detect/frame` RTT(warmup 후 25회, person-only): p50 64.7ms · p90 82.3ms · jitter(stdev) 8.3ms.",
        "- 동일 측정을 **워커 동시 실행 중**(multi_scene.mp4 를 5fps 카메라로 등록·기동)에도 반복: "
        "p50 64.1ms · p90 80.6ms · jitter 7.4ms — **차이 없음(오차범위 내)**. 이 환경에서는 "
        "DETECT_LOCK 직렬화로 인한 체감 지연이 안 잡혔다.",
        "- 적응형 최소주기(`VIGENT_DETECT_MIN_DYN=max(100, p50×1.2)`, index_local.html:753)는 이 RTT "
        "수준(65ms)에서 항상 100ms 바닥에 걸린다 — 즉 실배포 검출 갱신 주기는 오늘 앵커 제거와 무관하게 "
        "원래부터 ~100ms(10fps)였다(코드 무변경 확인).",
        "- **결론(a)**: 이 환경 실측으로는 검출 갱신주기 저하·서버 경합 증거를 못 찾았다. 다만 이 서버가 "
        "맥 실배포보다 빠를 수 있어(추론 백엔드·하드웨어 차이) 맥에서 재현 안 된다고 단정할 수는 없다 — "
        "모른다, 맥 실측 필요.",
    ]

    out = _HERE / "local_slowdown_investigate.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
