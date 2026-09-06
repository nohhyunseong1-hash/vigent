"""benchmarks/person_miss_baseline.py — person 박스 "놓침" 정량화 baseline (측정 전용, 코드 무수정).

목적: "놓침 0"이 아니라 "놓침 최소화+빠른복구" 개선 여지를 숫자로 판단하기 위한 baseline.
  - 트랙 커버리지: 물리적 person 각각의 관측 구간(span) 중 실제 검출이 있었던 프레임 비율.
  - 놓침 지속시간: 검출이 끊긴 순간부터 재검출까지의 시간(ms).
  - 원인 분해(다중라벨, 기하·픽셀 실측 기반 — 추측 라벨링 없음):
      가림   = 놓침 직전 프레임에 다른 person 박스가 IoU>0.15로 겹쳐 있었다(실측 기하).
      빠른이동 = 놓침 직전 속도(px/s)가 이 클립의 '빠름' 경계(global_speed_thresholds 상위33%) 이상.
      방향전환 = 놓침 직전 두 구간의 속도벡터 내적<0(급반전).
      모션블러 = 놓침 직전 프레임의 person crop Laplacian 분산이 이 클립 자체 중앙값의 50% 미만
                (실제 비디오 프레임 픽셀에서 cv2로 계산 — 상대적 클립-내 비교이지 절대 블러량 아님, 정직 고지).
  다인(multi_scene)은 tid 파편화가 심해(직전 보고) "물리적 person"을 tid 스트림만으로 못 얻는다 —
  이 스크립트는 track_fragmentation_causes.py 와 동일한 공간중접 기준(PROXIMITY_RATIO=0.6·
  LOOKBACK_FRAMES=15)으로 파편화된 tid를 하나의 "신원 체인"으로 이어붙인 뒤 그 체인 단위로 커버리지를
  잰다 — 재식별 알고리즘을 실제 코드에 넣는 게 아니라 측정 전용 후처리다(guard.py 무수정).
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
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

PROXIMITY_RATIO = 0.6     # track_fragmentation_causes.py 와 동일값(재사용, 신규 임의값 아님)
LOOKBACK_FRAMES = 15      # 상동
BLUR_REL_THRESHOLD = 0.5  # 클립 자체 중앙값 대비 상대 임계(절대 블러량 아님 — 정직 고지)


def _center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _diag(box: list[float]) -> float:
    return (box[2] ** 2 + box[3] ** 2) ** 0.5 or 1.0


def _center_near(a: list[float], b: list[float], ratio: float) -> bool:
    ax, ay = _center(a)
    bx, by = _center(b)
    d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    avg_diag = (_diag(a) + _diag(b)) / 2.0
    return avg_diag > 0 and d <= ratio * avg_diag


def build_identity_chains(frames: list[dict[str, Any]]) -> list[list[int]]:
    """파편화된 tid 들을 공간중접 기준으로 체인으로 묶는다(측정 전용 후처리, 재식별 알고리즘 아님)."""
    first_idx: dict[int, int] = {}
    first_box: dict[int, list[float]] = {}
    last_idx: dict[int, int] = {}
    last_box: dict[int, list[float]] = {}
    for i, f in enumerate(frames):
        for d in f["dets"]:
            if d["cls"] != "person":
                continue
            if d["tid"] not in first_idx:
                first_idx[d["tid"]] = i
                first_box[d["tid"]] = d["box"]
            last_idx[d["tid"]] = i
            last_box[d["tid"]] = d["box"]

    tids_sorted = sorted(first_idx, key=lambda t: first_idx[t])
    chains: list[list[int]] = []
    for tid in tids_sorted:
        fi = first_idx[tid]
        fb = first_box[tid]
        candidates: list[tuple[float, int]] = []
        for ci, chain in enumerate(chains):
            tail = chain[-1]
            gap = fi - last_idx[tail]
            if gap < 0 or gap > LOOKBACK_FRAMES:
                continue
            v = bq._iou_xywh(last_box[tail], fb)
            near = _center_near(last_box[tail], fb, PROXIMITY_RATIO)
            if v > 0.15 or near:
                candidates.append((v, ci))
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            chains[candidates[0][1]].append(tid)
        else:
            chains.append([tid])

    return chains


def _person_boxes_at(frame: dict[str, Any]) -> list[dict[str, Any]]:
    return [d for d in frame["dets"] if d["cls"] == "person"]


def _crop_sharpness(video_frames_gray: list, box: list[float], w: int, h: int) -> float | None:
    import numpy as np
    x, y, bw, bh = box
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(w, int(x + bw)), min(h, int(y + bh))
    if x1 - x0 < 8 or y1 - y0 < 8 or video_frames_gray is None:
        return None
    crop = video_frames_gray[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    import cv2
    lap = cv2.Laplacian(crop, cv2.CV_64F)
    return float(np.var(lap))


def analyze_clip(frames: list[dict[str, Any]], fps: float, video_path: Path | None) -> dict[str, Any]:
    chains = build_identity_chains(frames)
    speed_thresholds = bq.global_speed_thresholds(frames)
    fast_q = speed_thresholds[1]

    n = len(frames)
    dt_ms = 1000.0 / fps

    # 프레임별 person 박스(체인 무관, 원시) — occlusion 판정용
    frame_persons = [_person_boxes_at(f) for f in frames]

    # 프레임을 순회하며 crop sharpness 를 지연평가(필요한 프레임만 비디오에서 읽음)
    all_sharp_samples: list[float] = []
    cap = None
    w = h = 0
    if video_path is not None and video_path.exists():
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def get_gray(idx: int):
        if cap is None:
            return None
        cap.set(1, idx)  # cv2.CAP_PROP_POS_FRAMES
        ok, img = cap.read()
        if not ok:
            return None
        import cv2 as _cv2
        return _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)

    # 클립 전체 person crop sharpness 중앙값(상대 임계 기준선) — 매 프레임이 아니라 표본(성능)
    if cap is not None:
        sample_idxs = list(range(0, n, max(1, n // 60)))
        for idx in sample_idxs:
            gray = get_gray(idx)
            for d in frame_persons[idx]:
                sh = _crop_sharpness(gray, d["box"], w, h)
                if sh is not None:
                    all_sharp_samples.append(sh)
    median_sharp = sorted(all_sharp_samples)[len(all_sharp_samples) // 2] if all_sharp_samples else None

    total_span = 0
    total_occupied = 0
    gap_events: list[dict[str, Any]] = []

    for chain in chains:
        member_frames: dict[int, list[float]] = {}   # frame_idx -> box(첫 det만, 체인 내 유일하다고 가정)
        for tid in chain:
            for i, f in enumerate(frames):
                for d in f["dets"]:
                    if d["cls"] == "person" and d["tid"] == tid:
                        member_frames[i] = d["box"]
        if not member_frames:
            continue
        span0, span1 = min(member_frames), max(member_frames)
        span_len = span1 - span0 + 1
        occupied = len(member_frames)
        total_span += span_len
        total_occupied += occupied

        # 놓침 구간(연속 미검출) 탐색
        i = span0
        while i <= span1:
            if i in member_frames:
                i += 1
                continue
            gap_start = i
            while i <= span1 and i not in member_frames:
                i += 1
            gap_end = i - 1   # inclusive
            dur_ms = (gap_end - gap_start + 1) * dt_ms
            pre_idx = gap_start - 1   # 놓침 직전 마지막 관측 프레임(체인 내)
            pre_box = member_frames.get(pre_idx)
            if pre_box is None:
                continue   # 체인 시작 이전(있을 수 없지만 방어)

            causes = []
            # 가림: 놓침 직전 프레임에 다른 person 박스와 IoU>0.15
            for d in frame_persons[pre_idx]:
                if d["tid"] not in chain and bq._iou_xywh(d["box"], pre_box) > 0.15:
                    causes.append("가림")
                    break
            # 빠른이동/방향전환: 직전 2~3개 관측점으로 속도벡터 계산
            prior_idxs = sorted([k for k in member_frames if k <= pre_idx])[-3:]
            if len(prior_idxs) >= 2:
                b_last2 = [member_frames[k] for k in prior_idxs[-2:]]
                t_last2 = [frames[k]["t_cap_ms"] for k in prior_idxs[-2:]]
                c0, c1 = _center(b_last2[0]), _center(b_last2[1])
                dt_s = (t_last2[1] - t_last2[0]) / 1000.0
                speed = ((c1[0] - c0[0]) ** 2 + (c1[1] - c0[1]) ** 2) ** 0.5 / dt_s if dt_s > 0 else 0.0
                if speed >= fast_q:
                    causes.append("빠른이동")
                if len(prior_idxs) >= 3:
                    b_prev2 = [member_frames[k] for k in prior_idxs[-3:-1]]
                    cp0, cp1 = _center(b_prev2[0]), _center(b_prev2[1])
                    v_prev = (cp1[0] - cp0[0], cp1[1] - cp0[1])
                    v_last = (c1[0] - c0[0], c1[1] - c0[1])
                    if v_prev[0] * v_last[0] + v_prev[1] * v_last[1] < 0:
                        causes.append("방향전환")
            # 모션블러: 놓침 직전 프레임의 person crop 선명도가 클립 중앙값의 절반 미만(상대 비교)
            if cap is not None and median_sharp is not None:
                gray = get_gray(pre_idx)
                sh = _crop_sharpness(gray, pre_box, w, h)
                if sh is not None and sh < median_sharp * BLUR_REL_THRESHOLD:
                    causes.append("모션블러(상대)")

            gap_events.append({
                "chain": chain, "gap_start_idx": gap_start, "gap_end_idx": gap_end,
                "dur_ms": round(dur_ms, 1), "causes": causes or ["원인불명"],
            })

    if cap is not None:
        cap.release()

    coverage_pct = round(100 * total_occupied / total_span, 1) if total_span else None
    durs = [g["dur_ms"] for g in gap_events]
    cause_counts: dict[str, int] = {}
    for g in gap_events:
        for c in g["causes"]:
            cause_counts[c] = cause_counts.get(c, 0) + 1

    return {
        "n_chains": len(chains), "total_span_frames": total_span, "total_occupied_frames": total_occupied,
        "coverage_pct": coverage_pct, "n_gap_events": len(gap_events),
        "gap_dur_mean_ms": round(sum(durs) / len(durs), 1) if durs else None,
        "gap_dur_max_ms": round(max(durs), 1) if durs else None,
        "cause_counts": cause_counts, "gap_events": gap_events,
    }


def _report_clip(label: str, cache_name: str, video_path: Path) -> dict[str, Any] | None:
    cache_path = _HERE / "_sweep_cache" / f"{cache_name}.json"
    if not cache_path.exists():
        return None
    frames, fps = bq.load_detections_cache(cache_path)
    r = analyze_clip(frames, fps, video_path if video_path.exists() else None)
    r["label"] = label
    return r


def main() -> None:
    clips = [
        ("multi_scene(다인, 20.7s)", "multi_scene", media("runs/rfdetr/multi_scene.mp4")),
        ("mac_single_move 조밀(24fps)", "mac_single_move", media("runs/rfdetr/refset/mac_single_move.mp4.mp4")),
        ("mac_single_move 성김(~208ms)", "mac_single_move_sparse5", media("runs/rfdetr/refset/mac_single_move.mp4.mp4")),
    ]
    results = [_report_clip(label, name, video) for label, name, video in clips]

    lines = [
        "# Phase 1 — person 박스 '놓침' baseline (측정 전용, 코드 무수정)",
        "",
        "목표는 '놓침 0'이 아니라 '놓침 최소화+빠른복구' — 개선 여지를 숫자로 판단하기 위한 현재값.",
        "커버리지 = 물리적 person(파편화 tid를 공간중접 기준으로 체인으로 이어붙인 것) 관측구간 중 실제 "
        "검출 있었던 프레임 비율. 신원 체인은 track_fragmentation_causes.py 와 동일 기준"
        f"(PROXIMITY_RATIO={PROXIMITY_RATIO}·LOOKBACK_FRAMES={LOOKBACK_FRAMES})의 측정 전용 후처리다"
        "(guard.py에 재식별 알고리즘을 넣은 게 아님).",
        "",
        "| 지표 | " + " | ".join(r["label"] if r else "(캐시없음)" for r in results) + " |",
        "|---|" + "---|" * len(results),
    ]

    def cell(r, key, suffix=""):
        if r is None:
            return "(측정불가)"
        v = r[key]
        return "—" if v is None else f"{v}{suffix}"

    rows = [
        ("신원 체인 수(파편화 병합 후 물리적 person 추정치)", "n_chains", ""),
        ("전체 관측구간 프레임", "total_span_frames", ""),
        ("실제 검출된 프레임", "total_occupied_frames", ""),
        ("**트랙 커버리지**", "coverage_pct", "%"),
        ("놓침(gap) 이벤트 수", "n_gap_events", ""),
        ("놓침 평균 지속시간", "gap_dur_mean_ms", "ms"),
        ("놓침 최대 지속시간", "gap_dur_max_ms", "ms"),
    ]
    for label, key, suffix in rows:
        lines.append(f"| {label} | " + " | ".join(cell(r, key, suffix) for r in results) + " |")

    lines += ["", "## 놓침 원인 분해(다중라벨 — 한 이벤트가 여러 원인에 동시 해당 가능)", ""]
    for r in results:
        if r is None:
            continue
        lines.append(f"### {r['label']}")
        if not r["n_gap_events"]:
            lines.append("- 놓침 이벤트 0건(관측 안 됨).")
            lines.append("")
            continue
        for cause, cnt in sorted(r["cause_counts"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- {cause}: {cnt}건 ({round(100*cnt/r['n_gap_events'],1)}%)")
        lines.append("")

    lines += [
        "## 정직 고지",
        "- '가림'은 실측 기하(다른 person 박스와의 IoU)로 판정 — 실제 카메라 화면상 가림과 정확히 "
        "일치하지 않을 수 있다(다른 사람이 겹쳐 보이지만 IoU 임계를 못 넘는 경우 등).",
        "- '빠른이동'·'방향전환'은 놓침 직전 관측된 속도벡터 기반 — 놓침 구간 '동안' 실제로 무슨 일이 "
        "있었는지는 알 수 없다(그 구간은 정의상 검출이 없다).",
        "- '모션블러(상대)'는 절대적인 블러량이 아니라 **이 클립 자체의 person crop 선명도 중앙값 대비 "
        "상대 비교**다(Laplacian 분산, cv2 실측). 클립마다 기준선이 달라 클립 간 절대비교는 불가하다.",
        "- 원인 라벨이 전혀 안 붙는 '원인불명' 이벤트는 위 네 신호 중 어느 것도 감지 못한 경우다 — "
        "이는 '원인이 없다'가 아니라 '이 측정 방법으로는 못 잡았다'는 뜻이다.",
    ]

    out = _HERE / "person_miss_baseline.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
