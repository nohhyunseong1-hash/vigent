#!/usr/bin/env python3
"""benchmarks/bytetrack_empty_update_ab.py — [CODE_REVIEW M1-5] ByteTrack 빈 프레임 update 수정 전/후 A/B(측정 전용).

측정 대상(저장소 밖 VIGENT_DATA_DIR): runs/rfdetr/multi_scene.mp4 + runs/rfdetr/refset/ 4개.
각 영상을 bytetrack 모드로 프레임마다 guard.detect(person) 재생 → 프레임별 검출 캐시(JSON) →
  · 트랙 수(고유 tid) · 최대/평균 트랙 수명(초) · ID 스위치(연속 프레임 IoU≥0.5 매칭에서 tid 변경, box_quality.track_stability)
  · ★부활(revival): 같은 tid 가 gap_s(1.0s) 이상 사라졌다가 다시 나타난 횟수 — 이 수정이 직접 겨냥하는 현상
  · 사람 0명 프레임 수(수정이 영향을 주는 프레임)
multi_scene 은 Phase1.5 구간 지표(track_quality_baseline)도 함께.

사용:  python benchmarks/bytetrack_empty_update_ab.py --tag before   (수정 전 코드로)
       python benchmarks/bytetrack_empty_update_ab.py --tag after    (수정 후 코드로)
       python benchmarks/bytetrack_empty_update_ab.py --compare      (두 캐시 비교표 출력)
캐시: benchmarks/_sweep_cache/bt_empty_<tag>/<영상>.json (gitignore 대상). 산출은 숫자 표만(프레임·썸네일 없음).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import box_quality as bq  # noqa: E402
import track_quality_baseline as tqb  # noqa: E402
from data_paths import media  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

VIDEOS = {
    "multi_scene": "runs/rfdetr/multi_scene.mp4",
    "multi_cross": "runs/rfdetr/refset/multi_cross.mp4",
    "occlusion": "runs/rfdetr/refset/occlusion.mp4",
    "single_fast": "runs/rfdetr/refset/single_fast.mp4",
    "single_move": "runs/rfdetr/refset/mac_single_move.mp4.mp4",
}
GAP_S = 1.0


def replay(video: Path, cache: Path) -> tuple[list[dict[str, Any]], float, float]:
    if cache.exists():
        frames, fps = bq.load_detections_cache(cache)
        return frames, fps, 0.0
    import cv2
    import vision_loader
    from agents import build_agents

    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.TRACK_ALGO = "bytetrack"
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없음: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    guard.BYTETRACK_FRAME_RATE = float(fps)
    frames: list[dict[str, Any]] = []
    idx, t0 = 0, time.time()
    key = f"ab:{video.stem}"
    while True:
        ok, img = cap.read()
        if not ok:
            break
        h, w = img.shape[:2]
        out = guard.detect(img, detectors=["person"], track_key=key)
        dets = [{"cls": d.get("label"), "score": float(d.get("conf", 0.0)), "tid": int(d.get("tid", -1)),
                 "box": [round(v, 2) for v in (d["bbox"][0] * w, d["bbox"][1] * h,
                                                (d["bbox"][2] - d["bbox"][0]) * w, (d["bbox"][3] - d["bbox"][1]) * h)]}
                for d in out.get("detections", []) if d.get("bbox")]
        frames.append({"idx": idx, "t_cap_ms": (idx / fps) * 1000.0, "w": w, "h": h, "dets": dets})
        idx += 1
    cap.release()
    cache.parent.mkdir(parents=True, exist_ok=True)
    bq.save_detections_cache(cache, frames, fps)
    return frames, fps, time.time() - t0


def metrics(frames: list[dict[str, Any]], fps: float) -> dict[str, Any]:
    seen: dict[int, list[int]] = {}
    empty = 0
    for f in frames:
        ps = [d for d in f["dets"] if d["cls"] == "person"]
        if not ps:
            empty += 1
        for d in ps:
            seen.setdefault(d["tid"], []).append(f["idx"])
    life = [(v[-1] - v[0] + 1) / fps for v in seen.values()]
    gap_frames = GAP_S * fps
    revivals = sum(1 for v in seen.values() for a, b in zip(v, v[1:]) if (b - a) > gap_frames)
    stab = bq.track_stability(frames)
    return {"frames": len(frames), "fps": round(fps, 2), "empty_frames": empty,
            "tids": len(seen), "max_life_s": round(max(life), 2) if life else 0.0,
            "mean_life_s": round(sum(life) / len(life), 2) if life else 0.0,
            "id_switches": stab.get("switches"), "revivals": revivals}


def seg_metrics(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first: dict[int, float] = {}
    for f in frames:
        for d in f["dets"]:
            if d["cls"] == "person":
                first.setdefault(d["tid"], f["t_cap_ms"] / 1000.0)
    rows = []
    for seg in tqb.SEGMENTS:
        t0, t1 = seg["range"]
        sf = tqb._person_frames(frames, t0, t1)
        sw = tqb.id_switches_and_swaps(sf)
        fr = tqb.fragmentation(sf, first)
        occ = tqb.occlusion_retention(frames, (t0, t1))
        rows.append({"name": seg["name"], "switches": sw["switches"], "swaps": sw["swaps"],
                     "new_tracks": fr["new_tracks"], "retention_pct": occ["retention_pct"]})
    return rows


def run(tag: str) -> dict[str, Any]:
    out_dir = _HERE / "_sweep_cache" / f"bt_empty_{tag}"
    result: dict[str, Any] = {}
    for name, rel in VIDEOS.items():
        video = media(rel)
        if not video.exists():
            print(f"[{tag}] {name}: 없음({rel}) — 건너뜀")
            continue
        frames, fps, dt = replay(video, out_dir / f"{name}.json")
        m = metrics(frames, fps)
        if name == "multi_scene":
            m["segments"] = seg_metrics(frames)
        result[name] = m
        print(f"[{tag}] {name}: {m['frames']}f@{fps:.1f} tids={m['tids']} maxlife={m['max_life_s']}s "
              f"switches={m['id_switches']} revivals={m['revivals']} empty={m['empty_frames']}"
              + (f" ({dt:.1f}s)" if dt else " (캐시)"))
    (out_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def compare() -> None:
    a = json.loads((_HERE / "_sweep_cache" / "bt_empty_before" / "metrics.json").read_text(encoding="utf-8"))
    b = json.loads((_HERE / "_sweep_cache" / "bt_empty_after" / "metrics.json").read_text(encoding="utf-8"))
    print("| 영상 | 프레임(사람0 프레임) | 트랙 수 전→후 | 최대 수명 s 전→후 | 평균 수명 s 전→후 | ID 스위치 전→후 | 부활(≥1.0s 공백) 전→후 |")
    print("|---|---|---|---|---|---|---|")
    for name in VIDEOS:
        if name not in a or name not in b:
            continue
        x, y = a[name], b[name]
        print(f"| {name} | {x['frames']}({x['empty_frames']}) | {x['tids']}→{y['tids']} | {x['max_life_s']}→{y['max_life_s']} "
              f"| {x['mean_life_s']}→{y['mean_life_s']} | {x['id_switches']}→{y['id_switches']} | {x['revivals']}→{y['revivals']} |")
    if "multi_scene" in a and "multi_scene" in b:
        print("\n| multi_scene 구간 | ID스위치 전→후 | swap 전→후 | 신규트랙 전→후 | 가림후 유지율% 전→후 |")
        print("|---|---|---|---|---|")
        for ra, rb in zip(a["multi_scene"]["segments"], b["multi_scene"]["segments"]):
            print(f"| {ra['name']} | {ra['switches']}→{rb['switches']} | {ra['swaps']}→{rb['swaps']} "
                  f"| {ra['new_tracks']}→{rb['new_tracks']} | {ra['retention_pct']}→{rb['retention_pct']} |")


def gap_demo(legacy: bool, n_head: int = 120, n_gap: int = 120, n_tail: int = 120) -> dict[str, Any]:
    """통제 실험 — 실영상엔 사람 부재 구간이 없어(5개 영상 모두 빈 프레임 1개) A/B 차이가 0 이었다.
    multi_scene 앞 n_head 프레임 → **검은 프레임 n_gap 개(사람 0명)** → 이어지는 n_tail 프레임을 재생해
    부재 구간 뒤에 **앞 구간의 tid 가 부활하는지**를 센다. legacy=True 면 구 동작(빈 프레임에서 update
    미호출)을 몽키패치로 재현한다 — 같은 코드·같은 프레임으로 전/후를 비교하기 위함."""
    import cv2
    import numpy as np
    import vision_loader
    from agents import build_agents

    video = media(VIDEOS["multi_scene"])
    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.TRACK_ALGO = "bytetrack"
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    guard.BYTETRACK_FRAME_RATE = float(fps)
    if legacy:
        orig = guard._track_bytetrack

        def _legacy(fresh, track_key):        # 구 동작: person 0건이면 트래커 시간 정지
            if not any(str(d.get("label", "")).lower() == "person" for d in fresh):
                return guard._track_iou(fresh, track_key)
            return orig(fresh, track_key)
        guard._track_bytetrack = _legacy
    key = "gapdemo:" + ("legacy" if legacy else "fixed")
    head, tail = set(), set()
    blank = None
    for i in range(n_head + n_tail):
        ok, img = cap.read()
        if not ok:
            break
        if blank is None:
            blank = np.zeros_like(img)
        if i == n_head:
            for _ in range(n_gap):
                guard.detect(blank, detectors=["person"], track_key=key)
        out = guard.detect(img, detectors=["person"], track_key=key)
        tids = {d["tid"] for d in out.get("detections", []) if d.get("label") == "person" and d.get("tid") is not None}
        (head if i < n_head else tail).update(tids)
    cap.release()
    revived = head & tail
    return {"legacy": legacy, "fps": fps, "gap_s": round(n_gap / fps, 2),
            "buffer_s": round(guard.BYTETRACK_LOST_BUFFER / fps, 2),
            "head_tids": len(head), "tail_tids": len(tail), "revived": len(revived)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", choices=["before", "after"])
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--gap-demo", action="store_true")
    ns = ap.parse_args()
    if ns.tag:
        run(ns.tag)
    if ns.compare:
        compare()
    if ns.gap_demo:
        for legacy in (True, False):
            r = gap_demo(legacy)
            print(f"[gap-demo] {'구(legacy)' if legacy else '신(fixed)'}: 부재 {r['gap_s']}s(버퍼 {r['buffer_s']}s) "
                  f"앞구간 tid {r['head_tids']} · 뒷구간 tid {r['tail_tids']} · ★부활 {r['revived']}")
