#!/usr/bin/env python3
"""[P2b] 다인 추적 오프라인 평가 — ID 스위치·트랙 단절·재식별 성공률.

배경(감사 🟠C6): ByteTrack 을 채택했지만(PA) **다인 상황 검증이 미실시**였다. 실카메라 2인
시험은 사람이 필요하므로(docs/test_multiperson.md 로 분리), 저장소 내 다인 영상을 오프라인
재생해 정량 지표를 먼저 확보한다.

GT 라벨이 없으므로 **프록시 지표**를 쓴다(규칙7 — MOTA/IDF1 이라고 부르지 않는다):
  - **ID 스위치(추정)**: 연속 두 프레임에서 같은 위치(IoU≥0.5)의 트랙이 서로 다른 id 를
    가지면 1회로 센다. 정답 없이도 "같은 물체인데 id 가 바뀐" 사건을 잡는다.
  - **트랙 단절**: 확정 트랙이 사라졌다가 이후 같은 자리(IoU≥0.5)에 **다른 id** 로 다시
    나타난 횟수. 하나의 사람이 여러 조각으로 쪼개진 정도.
  - **재식별 성공**: 트랙이 사라졌다가 같은 자리에 **같은 id** 로 돌아온 횟수.
    성공률 = 재식별 성공 / (재식별 성공 + 트랙 단절).
  - 고유 tid 수·평균 인원수: 파편화 총량 지표(적을수록 안정).

두 알고리즘(iou / bytetrack)을 같은 영상으로 각각 돌려 나란히 비교한다.

사용:
    python scripts/eval_tracking.py                       # 기본 영상 3종
    python scripts/eval_tracking.py --video runs/rfdetr/refset/multi_cross.mp4
    python scripts/eval_tracking.py --max-frames 200      # 짧게(GPU 점유 최소화)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

DEFAULT_VIDEOS = [
    "runs/rfdetr/refset/multi_cross.mp4",     # 다인 교차
    "runs/rfdetr/refset/occlusion.mp4",       # 가림
    "runs/rfdetr/multi_scene.mp4",            # 다인 혼잡
]
MATCH_IOU = 0.5


def _iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def replay(video: Path, algo: str, max_frames: int | None) -> list[dict[str, Any]]:
    """영상을 재생하며 프레임별 person 트랙(id·bbox)을 수집."""
    import cv2
    import vision_loader
    from agents import build_agents

    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.TRACK_ALGO = algo
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    if algo == "bytetrack":
        # 재생은 매 비디오프레임마다 detect() 호출 → 버퍼 환산 기준을 영상 fps 로 맞춘다
        # (P2a: maximum_frames_without_update = int(frame_rate/30 * lost_track_buffer))
        guard.BYTETRACK_FRAME_RATE = float(fps)

    frames: list[dict[str, Any]] = []
    idx = 0
    while True:
        if max_frames is not None and idx >= max_frames:
            break
        ok, img = cap.read()
        if not ok:
            break
        out = guard.detect(img, detectors=["person"], track_key=f"eval:{algo}")
        frames.append({"idx": idx, "tracks": [
            {"tid": int(d.get("tid", -1)), "box": [float(v) for v in d.get("bbox", [0, 0, 0, 0])]}
            for d in out.get("detections", [])
            if str(d.get("label", "")).lower() == "person"]})
        idx += 1
    cap.release()
    return frames


def evaluate(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """프록시 지표 산출(GT 없음 — MOTA/IDF1 아님)."""
    id_switches = 0
    for i in range(1, len(frames)):
        for t in frames[i]["tracks"]:
            # 직전 프레임에서 같은 위치를 차지하던 트랙
            best, best_iou = None, 0.0
            for p in frames[i - 1]["tracks"]:
                v = _iou(t["box"], p["box"])
                if v > best_iou:
                    best, best_iou = p, v
            if best is not None and best_iou >= MATCH_IOU and best["tid"] != t["tid"]:
                id_switches += 1

    # 트랙 소멸 → 이후 같은 자리 재등장(같은 id=재식별 / 다른 id=단절)
    reid_ok = fragmented = 0
    last_seen: dict[int, tuple[int, list[float]]] = {}
    for i, f in enumerate(frames):
        present = {t["tid"] for t in f["tracks"]}
        for t in f["tracks"]:
            prev = last_seen.get(t["tid"])
            if prev and i - prev[0] > 1:
                reid_ok += 1                      # 같은 id 로 공백 후 복귀
            last_seen[t["tid"]] = (i, t["box"])
        # 사라진 트랙 자리에 다른 id 가 들어왔는가
        for tid, (li, box) in list(last_seen.items()):
            if tid in present or i - li != 1:
                continue
            for t in f["tracks"]:
                if t["tid"] != tid and _iou(box, t["box"]) >= MATCH_IOU:
                    fragmented += 1
                    break

    tids = {t["tid"] for f in frames for t in f["tracks"]}
    counts = [len(f["tracks"]) for f in frames]
    denom = reid_ok + fragmented
    return {
        "frames": len(frames),
        "unique_tids": len(tids),
        "avg_persons": round(sum(counts) / len(counts), 2) if counts else 0,
        "max_persons": max(counts) if counts else 0,
        "id_switches": id_switches,
        "fragmented": fragmented,
        "reid_ok": reid_ok,
        "reid_rate": round(reid_ok / denom * 100, 1) if denom else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="append", help="평가할 영상(여러 번 지정 가능)")
    ap.add_argument("--max-frames", type=int, default=None, help="프레임 수 상한(GPU 점유 최소화)")
    ap.add_argument("--out", default="benchmarks/eval_tracking_result.json")
    a = ap.parse_args()

    videos = [Path(_ROOT / v) for v in (a.video or DEFAULT_VIDEOS)]
    videos = [v for v in videos if v.exists()]
    if not videos:
        print("평가할 영상이 없습니다.")
        return 2

    results: dict[str, Any] = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                               "match_iou": MATCH_IOU, "videos": {}}
    print(f"{'영상':<38} {'algo':<10} {'고유tid':>7} {'ID스위치':>8} {'단절':>5} "
          f"{'재식별':>6} {'재식별률':>8} {'평균인원':>8}")
    print("-" * 100)
    for v in videos:
        results["videos"][v.name] = {}
        for algo in ("iou", "bytetrack"):
            fr = replay(v, algo, a.max_frames)
            m = evaluate(fr)
            results["videos"][v.name][algo] = m
            rr = f"{m['reid_rate']}%" if m["reid_rate"] is not None else "-"
            print(f"{v.name:<38} {algo:<10} {m['unique_tids']:>7} {m['id_switches']:>8} "
                  f"{m['fragmented']:>5} {m['reid_ok']:>6} {rr:>8} {m['avg_persons']:>8}")
        print()

    outp = _ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"결과 저장: {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
