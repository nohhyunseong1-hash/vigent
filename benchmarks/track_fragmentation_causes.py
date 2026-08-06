#!/usr/bin/env python3
"""benchmarks/track_fragmentation_causes.py — Phase1.5: 파편화(새 tid 발급) 원인 분해 (측정 전용).

Phase1 baseline(track_quality_baseline.md)이 잡은 person 고유 tid 42개(대부분 '파편화' —
기존 트랙이 끊기고 새 tid로 재등장) 각각에 대해, ByteTrack 도입 전 근본 원인을 갈라본다:

  (a) 검출미스형: 새 tid 등장 직전, 그 위치에 '검출 자체'가 최근 몇 프레임 동안 전혀 없었다
      → guard._track 의 매칭 로직과 무관하게 RF-DETR 이 그 사람을 놓친 것. ByteTrack 의 저신뢰
      2차매칭이 도움될 수 있는 케이스.
  (b) IoU붕괴형: 검출은 바로 직전 프레임까지 있었는데(연속), 그 박스와 새 박스의 IoU가
      guard.TRACK_IOU(0.45)·2차 완화기준(IoU≥0.25 또는 중심거리≤40%)을 둘 다 못 넘겨 매칭 실패
      → 검출은 됐지만 '너무 많이 움직여서' 못 이었다. ByteTrack 의 저신뢰 매칭은 여기 도움이
      안 된다(이미 고신뢰 검출이 있었는데도 실패한 것) — 근본 해결은 카메라 흔들림 감소(삼각대)
      또는 모션 예측(칼만필터) 쪽.
  (c) 매칭경합/이상치: 직전 프레임에 IoU≥0.45(1차 기준 충족)인 후보가 있었는데도 새 tid가
      발급된 경우 — 다른 검출과의 경합(그리디 1:1 매칭에서 밀림) 등 예외적 케이스. 별도 표기.

카메라 팬 정량화: 매 프레임 전이마다 dense optical flow(Farneback)를 계산해 배경 전역 이동량
(중앙값 벡터 크기, px)을 추정하고, (b)형 이벤트가 팬이 큰 프레임에 몰리는지 비교한다.

측정 전용 — guard.py·표시 코드 무수정.
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

TRACK_IOU = 0.45          # guard.GuardAgent.TRACK_IOU 와 동일값(재구현 아님 — 상수만 참조)
TRACK_IOU_2ND = 0.25      # 2차 완화매칭 IoU 기준
CENTER_NEAR_RATIO = 0.40  # 2차 완화매칭 중심거리 기준(대각선 비)
LOOKBACK_FRAMES = 15      # 검출미스 판단을 위한 최대 역탐 프레임(약 0.6초 @24fps)
PROXIMITY_RATIO = 0.6     # '근접' 판정(탐색 반경) — 2차 완화매칭 기준(0.40)보다 살짝 넓게만 잡아
                          # '거의 통과할 뻔한' 근접미스까지 포착하되, 화면 반대편 딴 사람은 배제.


def _center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _diag(box: list[float]) -> float:
    return (box[2] ** 2 + box[3] ** 2) ** 0.5 or 1.0


def _center_near(a: list[float], b: list[float], ratio: float) -> bool:
    """guard.py._center_near 와 동일 정의(평균 대각선 × ratio) — xywh 픽셀 좌표로 재계산(IoU/거리 비율은
    좌표계 무관하게 동일 결과가 나옴, guard 는 xyxy 정규화좌표 사용)."""
    ax, ay = _center(a)
    bx, by = _center(b)
    d = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    avg_diag = (_diag(a) + _diag(b)) / 2.0
    return avg_diag > 0 and d <= ratio * avg_diag


def find_fragmentation_events(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """전체 클립 기준 새 tid 첫 등장 이벤트. frame idx=0(클립 시작 시점 최초 가시인원)은
    '끊김'이 아니라 '최초 출현'이므로 제외(비교할 이전 프레임이 존재하지 않음)."""
    first_idx: dict[int, int] = {}
    first_box: dict[int, list[float]] = {}
    for i, f in enumerate(frames):
        for d in f["dets"]:
            if d["cls"] != "person":
                continue
            if d["tid"] not in first_idx:
                first_idx[d["tid"]] = i
                first_box[d["tid"]] = d["box"]
    events = []
    for tid, idx in first_idx.items():
        if idx == 0:
            continue
        events.append({"tid": tid, "idx": idx, "t": frames[idx]["t_cap_ms"] / 1000.0, "box": first_box[tid]})
    events.sort(key=lambda e: e["idx"])
    return events


def classify_event(frames: list[dict[str, Any]], ev: dict[str, Any]) -> dict[str, Any]:
    idx, box = ev["idx"], ev["box"]
    # 역탐: idx-1 부터 최대 LOOKBACK_FRAMES 프레임 전까지, '근접' person 검출을 찾는다(자기 tid 제외).
    nearest: dict[str, Any] | None = None
    for back in range(1, LOOKBACK_FRAMES + 1):
        j = idx - back
        if j < 0:
            break
        for d in frames[j]["dets"]:
            if d["cls"] != "person" or d["tid"] == ev["tid"]:
                continue
            if _center_near(d["box"], box, PROXIMITY_RATIO):
                iou = bq._iou_xywh(d["box"], box)
                cand = {"back": back, "iou": iou, "tid": d["tid"], "box": d["box"],
                        "center_near_2nd": _center_near(d["box"], box, CENTER_NEAR_RATIO)}
                if nearest is None or iou > nearest["iou"] or (iou == nearest["iou"] and back < nearest["back"]):
                    nearest = cand
        if nearest is not None and nearest["back"] == back:
            break   # 이 역탐 프레임에서 후보를 찾았으면 더 뒤는 안 봄(가장 가까운 시점 우선)

    if nearest is None:
        return {**ev, "cause": "a_검출미스", "evidence": f"직전 {LOOKBACK_FRAMES}프레임 내 근접검출 없음"}
    if nearest["iou"] >= TRACK_IOU:
        return {**ev, "cause": "c_매칭경합", "evidence": f"back={nearest['back']} IoU={nearest['iou']:.2f}(1차기준 충족했는데도 새tid)"}
    passed_2nd = nearest["iou"] >= TRACK_IOU_2ND or nearest["center_near_2nd"]
    tag = "c_매칭경합" if passed_2nd else "b_IoU붕괴"
    evidence = (f"back={nearest['back']}프레임({nearest['back']/24.0*1000:.0f}ms전) "
                f"IoU={nearest['iou']:.2f} 2차기준통과={passed_2nd}")
    return {**ev, "cause": tag, "evidence": evidence, "pred_box": nearest["box"], "back": nearest["back"]}


def compute_pan_series(video_path: Path, n_frames: int) -> list[float]:
    """프레임 i-1→i 배경 전역이동량(중앙값 flow 크기, px) 추정 — Farneback dense optical flow.
    전경 인물은 화면 대비 면적이 작아 중앙값이 배경(카메라 팬) 대표값에 가깝다(강건 통계)."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video_path))
    pans = [0.0]  # index0 은 이전 프레임 없음
    prev_gray = None
    i = 0
    while True:
        ok, img = cap.read()
        if not ok or i >= n_frames:
            break
        small = cv2.resize(img, (0, 0), fx=0.35, fy=0.35)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 2, 15, 2, 5, 1.1, 0)
            mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
            pans.append(float(np.median(mag)) / 0.35)   # 다운스케일 보정(원 해상도 px 환산)
        prev_gray = gray
        i += 1
    cap.release()
    return pans


def main() -> None:
    frames, fps = bq.load_detections_cache(Path("benchmarks/_sweep_cache/multi_scene.json"))
    events = find_fragmentation_events(frames)
    print(f"파편화 후보(최초출현 제외) {len(events)}건 / 전체 고유tid {len({d['tid'] for f in frames for d in f['dets'] if d['cls']=='person'})}개")

    classified = [classify_event(frames, ev) for ev in events]

    print("배경 optical flow(카메라 팬) 계산 중...", flush=True)
    pans = compute_pan_series(Path("runs/rfdetr/multi_scene.mp4"), len(frames))

    for c in classified:
        c["pan_px"] = pans[c["idx"]] if c["idx"] < len(pans) else None

    n_a = sum(1 for c in classified if c["cause"] == "a_검출미스")
    n_b = sum(1 for c in classified if c["cause"] == "b_IoU붕괴")
    n_c = sum(1 for c in classified if c["cause"] == "c_매칭경합")

    # S5(15.9~19.8s) 하위집합
    s5 = [c for c in classified if 15.9 <= c["t"] < 19.8]
    n_a5 = sum(1 for c in s5 if c["cause"] == "a_검출미스")
    n_b5 = sum(1 for c in s5 if c["cause"] == "b_IoU붕괴")
    n_c5 = sum(1 for c in s5 if c["cause"] == "c_매칭경합")

    # 팬 상관: b형 이벤트 팬 vs 전체 프레임 팬 분포
    all_pans = [p for p in pans if p > 0]
    all_pans_sorted = sorted(all_pans)

    def pct_rank(v: float) -> float:
        if not all_pans_sorted:
            return 0.0
        import bisect
        return 100.0 * bisect.bisect_left(all_pans_sorted, v) / len(all_pans_sorted)

    b_pans = [c["pan_px"] for c in classified if c["cause"] == "b_IoU붕괴" and c["pan_px"] is not None]
    a_pans = [c["pan_px"] for c in classified if c["cause"] == "a_검출미스" and c["pan_px"] is not None]

    mean_all = sum(all_pans) / len(all_pans) if all_pans else 0.0
    mean_b = sum(b_pans) / len(b_pans) if b_pans else 0.0
    mean_a = sum(a_pans) / len(a_pans) if a_pans else 0.0

    lines = [
        "# Phase1.5 — 파편화 원인 분해 (2026-08-06)",
        "",
        "> 측정 전용, 코드 무수정. ByteTrack 도입 전 '파편화 42건'의 근본 원인을 검출미스(a) vs "
        "IoU붕괴/카메라팬(b)로 분해한다.",
        "",
        "## 전체 분류",
        f"- 파편화 후보(클립 시작 시점 최초출현 4건 제외): **{len(events)}건**",
        f"- **(a) 검출미스형: {n_a}건 ({100*n_a/len(events):.0f}%)** — ByteTrack 저신뢰 2차매칭 유망",
        f"- **(b) IoU붕괴형: {n_b}건 ({100*n_b/len(events):.0f}%)** — 검출은 있었으나 이동량 과다, "
        "ByteTrack 저신뢰매칭 무관(고신뢰 검출끼리도 실패)",
        f"- (c) 매칭경합/이상치: {n_c}건 ({100*n_c/len(events):.0f}%) — 그리디 1:1 매칭 경합 등",
        "",
        "## S5(다인 파편화 핵심구간, 15.9~19.8s) 하위집계",
        f"- (a) 검출미스형: {n_a5}건 / (b) IoU붕괴형: {n_b5}건 / (c) 매칭경합: {n_c5}건 (전체 {len(s5)}건)",
        "",
        "## 카메라 팬 상관",
        f"- 전체 프레임전이 배경 팬(px, Farneback median) 평균 **{mean_all:.1f}px**",
        f"- (a)검출미스형 이벤트 시점 팬 평균 **{mean_a:.1f}px**(전체분포 상위 {100-pct_rank(mean_a) if a_pans else float('nan'):.0f}%tile 근방, n={len(a_pans)})",
        f"- (b)IoU붕괴형 이벤트 시점 팬 평균 **{mean_b:.1f}px**(전체분포 상위 {100-pct_rank(mean_b) if b_pans else float('nan'):.0f}%tile 근방, n={len(b_pans)})",
        "",
        "## 이벤트별 상세",
        "",
        "| tid | 시각(s) | 구간 | 원인 | 근거 | 팬(px) |",
        "|---|---|---|---|---|---|",
    ]

    def seg_of(t: float) -> str:
        for seg in [("S1", 0.0, 4.5), ("S2", 4.5, 8.9), ("S3", 8.9, 11.8), ("S4", 11.8, 15.9),
                    ("S5", 15.9, 19.8), ("S6", 19.8, 20.71)]:
            if seg[1] <= t < seg[2]:
                return seg[0]
        return "?"

    for c in classified:
        lines.append(f"| {c['tid']} | {c['t']:.2f} | {seg_of(c['t'])} | {c['cause']} | {c['evidence']} "
                     f"| {c['pan_px']:.1f} |" if c["pan_px"] is not None else
                     f"| {c['tid']} | {c['t']:.2f} | {seg_of(c['t'])} | {c['cause']} | {c['evidence']} | — |")

    n_total = len(events)
    lines += [
        "",
        "## 결론",
        "",
        f"**원 질문(a/b 이분법)에 대한 답 + 예상 밖 제3의 원인 발견.** (a)검출미스 {n_a}건({100*n_a/n_total:.0f}%) "
        f"vs (b)IoU붕괴 {n_b}건({100*n_b/n_total:.0f}%)에 더해, **(c)매칭경합이 {n_c}건({100*n_c/n_total:.0f}%)"
        "으로 (b)와 거의 동률**이었다 — 직전 프레임에 IoU 0.4~0.9(1차기준 0.45를 넘는 경우도 다수)의 명백한 "
        "동일인 후보가 있었는데도 새 tid가 발급된 경우다. `guard._track()`이 **그리디 1:1 매칭**(첫 발견 순서대로 "
        "확정, 전역 최적화 없음)이라, 여러 검출이 한 트랙을 동시에 두고 경합하면 진짜 정답이 아닌 쪽이 이겨서 "
        "다른 하나가 새 트랙으로 밀려나는 것으로 보인다.",
        "",
        f"- **(a)+(c) = {n_a+n_c}건({100*(n_a+n_c)/n_total:.0f}%)은 매칭 알고리즘 개선으로 해결 가능한 범주**"
        "다 — (a)는 ByteTrack 의 저신뢰 2차매칭(검출은 약하게라도 있었다면 회수), (c)는 전역 최적할당"
        "(Hungarian 등, 그리디의 경합패배 문제를 원천 해결)이 각각 대응하는 실패모드다.",
        f"- **(b) = {n_b}건({100*n_b/n_total:.0f}%)은 순수 기하학적 한계**(검출은 있었으나 이동량이 임계를 넘음) — "
        "매칭 알고리즘만으로는 못 고치고, **모션예측(칼만필터로 다음 위치를 미리 추정)**이 있어야 한다.",
        "- **`trackers.ByteTrackTracker` 소스에 칼만필터 사용이 확인됨**(`trackers/core/bytetrack/tracker.py`) "
        "— 즉 ByteTrack 도입은 (a)뿐 아니라 (b)에도 원리적으로 도움될 가능성이 있다(저신뢰매칭 때문이 아니라 "
        "모션예측 때문에). 이 부분은 Phase1.5(정적 분석)로는 확정할 수 없고 **Phase2 A/B 실측으로만 검증 가능**.",
        "",
        f"- **종합**: (a)+(b)+(c) = {n_a}+{n_b}+{n_c} = {n_total}건 전부가 어떤 형태로든 ByteTrack 의 두 축"
        "(저신뢰매칭·전역최적할당) 또는 그 구현에 포함된 칼만필터로 개선될 여지가 있어 보인다 — "
        "**원 질문의 '(b)면 무익' 전제가 이번 실측으로는 뒷받침되지 않는다.** 다만 이건 '가능성'이지 '확정'이 "
        "아니다 — 그리디 vs 전역최적, 칼만필터 유무의 실질 효과는 Phase2 A/B 로 직접 재야 한다.",
        "- (참고: 최종 판단·Phase2 진행 여부는 자동분류가 아니라 이 표+수치를 사용자가 검토해 결정)",
    ]

    out = Path("benchmarks/track_fragmentation_causes.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"\n... (표 전체는 파일 참고)\n저장: {out}")


if __name__ == "__main__":
    main()
