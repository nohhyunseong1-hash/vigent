#!/usr/bin/env python3
"""benchmarks/box_quality_sweep.py — Phase2A 후보 파라미터 스윕 (측정 전용).

box_quality.py 의 Part A/B/C 함수를 그대로 재사용해, BoxTracker 옵션 후보값들을 비교한다.
검출(Part A)은 영상당 1회만 실행해 캐시하고, 표시재생(Part B)만 후보 수만큼 반복한다 —
무거운 guard.detect() 재실행 없이 빠르게 여러 후보를 비교하기 위한 스윕 전용 도구.

이 스크립트는 아무것도 자동 채택하지 않는다 — 사람이 출력을 보고 판단 후, 채택된 값만
vigent-core/static/vigent-box-display.js 의 기본값으로 반영하고(별도 커밋), box_quality.py
로 전체 5시나리오 전/후 리포트를 재생성해 회귀를 확인한다.

사용(400ms 결정 시나리오만, 빠름):
  python3 benchmarks/box_quality_sweep.py --variants '{"base":{}, "cap1.0":{"extrapCap":1.0}}'

전 시나리오 비교:
  python3 benchmarks/box_quality_sweep.py --variants '{...}' --all-scenarios
"""
from __future__ import annotations

import argparse
import json
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

VIDEOS = [
    ("test_fast", _ROOT / "runs" / "rfdetr" / "test_fast.mp4"),
    ("test_walk", _ROOT / "runs" / "rfdetr" / "test_walk.mp4"),
]
DECISION_SCENARIO = "d400"


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase2A 후보 파라미터 스윕(측정 전용)")
    p.add_argument("--variants", required=True, help='JSON: {"이름": {BoxTracker opts...}, ...}')
    p.add_argument("--node-bin", default="node")
    p.add_argument("--cache-dir", default=str(_HERE / "_sweep_cache"))
    p.add_argument("--all-scenarios", action="store_true", help="d400 만이 아니라 5시나리오 전부 비교")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--detect-cadence-ms", type=float, default=0,
                   help="ingest 캐던스(ms). 0=매프레임(원본). 100=실배포 DETECT_MIN_INTERVAL_MS 재현")
    return p.parse_args()


def _fmt(v: float | None, nd: int = 1) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def _ensure_cache(tag: str, video: Path, cache_dir: Path) -> tuple[list[dict[str, Any]], float]:
    cache_path = cache_dir / f"{tag}.json"
    if cache_path.exists():
        return bq.load_detections_cache(cache_path)
    frames, fps, _dt = bq.replay_detections(video, ["person"], f"boxq:{tag}", None, None, 0)
    cache_dir.mkdir(parents=True, exist_ok=True)
    bq.save_detections_cache(cache_path, frames, fps)
    return frames, fps


def _row(name: str, m: dict[str, Any]) -> str:
    b = m["buckets"]["빠름"]
    return (f"| {name} | {_fmt(b['p50'])}/{_fmt(b['p95'])} | {_fmt(m['freeze_pct'])} "
            f"| {_fmt(m['overlap_pct'])} | {_fmt(m['overshoot_p50'])}/{_fmt(m['overshoot_p95'])}"
            f"({m['overshoot_n']}) |")


def main() -> None:
    a = _args()
    variants: dict[str, dict[str, Any]] = json.loads(a.variants)
    cache_dir = Path(a.cache_dir)
    scenarios = bq.SCENARIOS if a.all_scenarios else [s for s in bq.SCENARIOS if s["name"] == DECISION_SCENARIO]

    for tag, video in VIDEOS:
        frames, _fps = _ensure_cache(tag, video, cache_dir)
        ingest_frames = bq.subsample_for_ingest(frames, a.detect_cadence_ms)
        thresholds = bq.global_speed_thresholds(frames)
        cadence_note = f" (ingest 캐던스 {a.detect_cadence_ms:.0f}ms, {len(frames)}→{len(ingest_frames)})" \
            if a.detect_cadence_ms > 0 else ""
        for sc in scenarios:
            print(f"\n=== {tag} — {sc['label']} — 후보 비교{cadence_note} ===")
            print("| 후보 | 빠름p50/p95 | 정지% | 겹침% | 오버슈트p50/p95(n) |")
            print("|---|---|---|---|---|")
            for name, opts in variants.items():
                vis = bq.run_display_scenario(ingest_frames, sc, a.node_bin, None, a.seed, opts)
                m = bq.compute_metrics(frames, vis, thresholds)
                print(_row(name, m))


if __name__ == "__main__":
    main()
