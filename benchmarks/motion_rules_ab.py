#!/usr/bin/env python3
"""benchmarks/motion_rules_ab.py — [CODE_REVIEW M2-2·M2-3] 급격동작·무동작 규칙 수정 전/후 A/B(측정 전용).

입력: bytetrack_empty_update_ab.py 가 만든 프레임별 검출 캐시(benchmarks/_sweep_cache/bt_empty_after/<영상>.json,
      ByteTrack tid 포함, 저장소 밖 영상 5개). 워커 캐던스(2fps)로 표본화해 MotionTracker 에 넣는다.
  · 구(legacy): tid 를 지우고 넣는다 → 중심점 최근접(0.32) 매칭 = 수정 전 동작 그대로. y 보정 없음.
  · 신(fixed):  tid 그대로 + aspect_hw 보정.
지표: rapid_motion / immobility 프레임 단위 발화 수 + 15s 쿨다운 적용 이벤트 수(발화 시각 초),
      ID 스왑(구 동작에서 중심점 매칭이 실제 tid 와 다른 트랙에 붙은 횟수).
산출은 숫자만(프레임·경로 없음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import worker as W  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CACHE = _HERE / "_sweep_cache" / "bt_empty_after"
VIDEOS = ["multi_scene", "multi_cross", "occlusion", "single_fast", "single_move"]
WORKER_FPS = 2.0
COOLDOWN_S = 15.0


def _dets(frame: dict[str, Any], keep_tid: bool) -> list[dict[str, Any]]:
    w, h = frame["w"], frame["h"]
    out = []
    for d in frame["dets"]:
        if d["cls"] != "person":
            continue
        x, y, bw, bh = d["box"]
        det = {"label": "person", "conf": d["score"], "bbox": [x / w, y / h, (x + bw) / w, (y + bh) / h]}
        if keep_tid and d["tid"] >= 0:            # 캐시의 -1(미확정)은 운영에선 tid 없음(None)과 같다
            det["tid"] = d["tid"]
        out.append(det)
    return out


def _legacy_swaps(samples: list[tuple[float, list[dict[str, Any]]]], match: float) -> int:
    """구 동작(중심점 최근접 < match)이 실제 tid 와 다른 트랙에 붙은 횟수."""
    tracks: list[dict[str, Any]] = []
    swaps = 0
    for ts, dets in samples:
        used: set[int] = set()
        for d in dets:
            cx, cy = (d["bbox"][0] + d["bbox"][2]) / 2, (d["bbox"][1] + d["bbox"][3]) / 2
            best, bd = None, 1e9
            for k, tr in enumerate(tracks):
                if k in used:
                    continue
                dd = ((cx - tr["cx"]) ** 2 + (cy - tr["cy"]) ** 2) ** 0.5
                if dd < bd:
                    bd, best = dd, k
            if best is not None and bd < match:
                tr = tracks[best]
                used.add(best)
                if tr["tid"] != d["tid"]:
                    swaps += 1
                    tr["tid"] = d["tid"]
            else:
                tr = {"tid": d["tid"]}
                tracks.append(tr)
                used.add(len(tracks) - 1)
            tr["cx"], tr["cy"], tr["ts"] = cx, cy, ts
        tracks = [t for t in tracks if ts - t["ts"] < 3.0]
    return swaps


def run_one(name: str) -> dict[str, Any]:
    data = json.loads((CACHE / f"{name}.json").read_text(encoding="utf-8"))
    fps, frames = data["fps"], data["frames"]
    step = max(1, int(round(fps / WORKER_FPS)))
    samples = [(f["t_cap_ms"] / 1000.0, f) for f in frames[::step]]
    aspect = frames[0]["h"] / frames[0]["w"] if frames else 1.0
    res: dict[str, Any] = {"frames": len(frames), "fps": round(fps, 2), "samples": len(samples),
                           "aspect_hw": round(aspect, 4)}
    for mode in ("legacy", "fixed"):
        mt = W.MotionTracker()
        if mode == "legacy":
            mt.RAPID_T_SLACK = 0.0                # 구 동작 재현: 창 여유 없음(tid 는 이미 지움 → 중심점 매칭)
        raw = {"rapid_motion": [], "immobility": []}
        last = {"rapid_motion": -1e9, "immobility": -1e9}
        events = {"rapid_motion": [], "immobility": []}
        detail: list[str] = []          # 급격동작 발화별 (시각, tid, 이동량) — 어떤 발화가 사라지고 생겼는지
        ar = aspect if mode == "fixed" else 1.0
        for ts, f in samples:
            dets = _dets(f, keep_tid=(mode == "fixed"))
            fired = mt.update(dets, ts, aspect_hw=(aspect if mode == "fixed" else None))
            for r, _lv, _n in fired:
                raw[r].append(round(ts, 2))
                if ts - last[r] >= COOLDOWN_S:
                    last[r] = ts
                    events[r].append(round(ts, 2))
            if any(r == "rapid_motion" for r, *_ in fired):
                for tr in mt._tracks:                       # 발화 트랙 특정(측정 전용 내부 접근)
                    rec = [x for x in tr["hist"] if 0 <= ts - x[0] <= mt.RAPID_T + mt.RAPID_T_SLACK]
                    if len(rec) >= 2:
                        dx, dy = rec[-1][1] - rec[0][1], (rec[-1][2] - rec[0][2]) * ar
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist > mt.RAPID_DIST:
                            detail.append(f"{ts:.1f}s tid={tr.get('tid')} d={dist:.2f}")
        res[mode] = {"rapid_raw": len(raw["rapid_motion"]), "rapid_events": events["rapid_motion"],
                     "rapid_raw_ts": raw["rapid_motion"], "rapid_detail": detail,
                     "immob_raw": len(raw["immobility"]), "immob_events": events["immobility"]}
    res["legacy_swaps"] = _legacy_swaps([(ts, _dets(f, True)) for ts, f in samples], W.MotionTracker.MATCH)
    return res


def main() -> None:
    print("| 영상 | 표본(2fps) | 급격동작 프레임발화 구→신 | 급격동작 이벤트(15s 쿨다운) 구→신 · 시각(초) | 무동작 구→신 | 구 동작 ID 스왑 |")
    print("|---|---|---|---|---|---|")
    for name in VIDEOS:
        if not (CACHE / f"{name}.json").exists():
            continue
        r = run_one(name)
        lg, fx = r["legacy"], r["fixed"]
        print(f"| {name} | {r['samples']}/{r['frames']}f | {lg['rapid_raw']}→{fx['rapid_raw']} "
              f"| {len(lg['rapid_events'])}→{len(fx['rapid_events'])} · 구 {lg['rapid_events']} / 신 {fx['rapid_events']} "
              f"| {lg['immob_raw']}→{fx['immob_raw']} | {r['legacy_swaps']} |")
    print("\n발화 상세(프레임 단위, 시각·tid·이동량 — 구 동작은 tid 없이 매칭하므로 tid=None):")
    for name in VIDEOS:
        if not (CACHE / f"{name}.json").exists():
            continue
        r = run_one(name)
        print(f"- {name}: 구 {r['legacy']['rapid_detail']}")
        print(f"  {' ' * len(name)}  신 {r['fixed']['rapid_detail']}")


if __name__ == "__main__":
    main()
