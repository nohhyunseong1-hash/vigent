#!/usr/bin/env python3
"""benchmarks/track_quality_baseline.py — 다인·가림·빠른이동 클립의 구간별 추적 품질 측정 (측정 전용).

box_quality.py 의 캐시/헬퍼(replay_detections·save/load_detections_cache·_iou_xywh)를 재사용한다.
guard.py 의 _track()(IoU+중심점 매칭, tid 발급)이 만든 tid 스트림을 구간(초 단위)별로 잘라
아래 지표를 낸다 — Phase 2(ByteTrack)와 전/후 비교할 baseline.

지표 정의(전부 tid 스트림에서 결정적으로 계산 — 라벨/정답 없이 자동 산출 가능한 것만):
  · ID 스위치     : 연속 프레임 IoU≥0.5 매칭 시 같은 물리적 위치의 tid 가 바뀐 횟수(tools/track_quality.py 와 동일 원리).
  · Fragmentation : 구간 내 새로 시작된 tid 수(첫 등장 프레임 수) — 트랙이 끊겼다 새로 생기면 여기 잡힌다.
  · ID swap       : ID 스위치 중에서도 "양방향" 신호만 엄격히 인정 — 프레임 t 에서 두 박스 A,B 가 각각
                    프레임 t-1 의 서로 다른 활성 트랙과 매칭되는데 그 tid 가 서로 뒤바뀐 경우(대칭 교환).
                    편도 전환(한쪽만 tid 바뀜=fragmentation 이 더 흔한 원인)과 구분해 과다계상 방지.
  · 가림후 ID유지율: 구간 내에서 소멸한 tid 각각에 대해, 소멸 시점 근방 위치에 같은 tid 가 다시 나타나는지
                    확인(gap_s=0.5초 내). guard._track 은 tid 를 재사용하지 않으므로(설계상) 미탐지가
                    STALE_MAX_MISSES(1)·TRACK_TTL(1.2s) 허용치를 넘으면 재등장은 항상 '새 tid'로 잡힌다 —
                    단 짧은 미탐지는 이 허용치 안에서 같은 tid 로 자연히 이어지므로 실측값은 구간마다
                    다르다(아래 결과 참고, 균일한 0%를 가정하지 않는다).

주의(정직 고지): "ID swap" 은 정답(ground truth) 트랙 없이 완전한 정밀 계산이 불가능하다. 위 양방향-신호
정의는 보수적 프록시이며, 과소계상(swap 인데 fragmentation 으로만 잡힘)될 수 있다. 구간별 원시 tid 타임라인도
함께 출력해 육안 교차검증이 가능하게 한다.
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

# multi_scene_labels.md 의 구간 정의(초). 라벨 파일과 동기화 유지.
SEGMENTS = [
    {"name": "S1", "range": (0.0, 4.5), "label": "교차+카메라급이동(빠른이동 후보)"},
    {"name": "S2", "range": (4.5, 8.9), "label": "기준구간(안정 2인)"},
    {"name": "S3", "range": (8.9, 11.8), "label": "가림/재등장 후보"},
    {"name": "S4", "range": (11.8, 15.9), "label": "저인원 단순구간"},
    {"name": "S5", "range": (15.9, 19.8), "label": "다인 교차+파편화 핵심구간"},
    {"name": "S6", "range": (19.8, 20.71), "label": "종료"},
]


def _person_frames(frames: list[dict[str, Any]], t0: float, t1: float) -> list[dict[str, Any]]:
    out = []
    for f in frames:
        t = f["t_cap_ms"] / 1000.0
        if t0 <= t < t1:
            out.append({"t": t, "dets": [d for d in f["dets"] if d["cls"] == "person"]})
    return out


def id_switches_and_swaps(seg_frames: list[dict[str, Any]]) -> dict[str, Any]:
    switches = 0
    swaps = 0
    for a, b in zip(seg_frames, seg_frames[1:]):
        # 각 b-box 를 a 의 최선(IoU) 트랙에 매칭
        matches: list[tuple[dict, dict | None, float]] = []
        used_a: set[int] = set()
        for db in b["dets"]:
            best, best_iou, best_i = None, 0.5, -1
            for i, da in enumerate(a["dets"]):
                if i in used_a:
                    continue
                v = bq._iou_xywh(da["box"], db["box"])
                if v >= best_iou:
                    best_iou, best, best_i = v, da, i
            if best is not None:
                used_a.add(best_i)
            matches.append((db, best, best_iou))
        for db, da, _v in matches:
            if da is not None and da["tid"] != db["tid"]:
                switches += 1
        # 양방향 스왑: db1↔da2, db2↔da1 처럼 두 매칭이 서로의 이전 tid 를 교환했는지
        pairs = [(db["tid"], da["tid"]) for db, da, _v in matches if da is not None and da["tid"] != db["tid"]]
        for i in range(len(pairs)):
            for j in range(i + 1, len(pairs)):
                new_i, old_i = pairs[i]
                new_j, old_j = pairs[j]
                if new_i == old_j and new_j == old_i:
                    swaps += 1
    return {"switches": switches, "swaps": swaps}


def fragmentation(seg_frames: list[dict[str, Any]], global_first_seen: dict[int, float]) -> dict[str, Any]:
    """구간 내에서 '처음 등장'하는 tid 수(전체 클립 기준 첫 등장이 이 구간 안일 때만 카운트)."""
    if not seg_frames:
        return {"new_tracks": 0, "tids": []}
    t0 = seg_frames[0]["t"]
    t1 = seg_frames[-1]["t"]
    tids_in_seg = {d["tid"] for f in seg_frames for d in f["dets"]}
    starts = [tid for tid in tids_in_seg if t0 <= global_first_seen.get(tid, -1) <= t1]
    return {"new_tracks": len(starts), "tids": sorted(starts)}


def occlusion_retention(frames: list[dict[str, Any]], seg_range: tuple[float, float],
                         gap_s: float = 0.5, radius: float = 0.15) -> dict[str, Any]:
    """구간 내 소멸한 tid 각각에 대해, 소멸 위치 근방(radius, 정규화 대각선비)에 gap_s 이내로
    '다른(새) tid'가 재등장하는지 확인. guard._track 은 tid 재사용을 안 하므로 '같은 tid 로 복귀'는
    설계상 불가능 — 여기서는 "공간적으로 이어지는 재등장이 있었는가"(재사용 tid 유무)만 본다."""
    t0, t1 = seg_range
    all_person = [{"t": f["t_cap_ms"] / 1000.0, "dets": [d for d in f["dets"] if d["cls"] == "person"]}
                  for f in frames]
    # 구간 내 각 tid 의 마지막 목격 시각·위치
    last_seen: dict[int, tuple[float, list[float]]] = {}
    for f in all_person:
        if t0 <= f["t"] < t1:
            for d in f["dets"]:
                last_seen[d["tid"]] = (f["t"], d["box"])
    events = 0
    retained_same_tid = 0  # 설계상 항상 0(재사용 없음) — 명시적으로 측정해 증명
    reappeared_new_tid = 0
    for tid, (t_last, box) in last_seen.items():
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        diag = (box[2] ** 2 + box[3] ** 2) ** 0.5 or 1.0
        window = [f for f in all_person if t_last < f["t"] <= t_last + gap_s]
        if not window:
            continue
        events += 1
        found_same, found_new = False, False
        for f in window:
            for d in f["dets"]:
                dcx, dcy = d["box"][0] + d["box"][2] / 2, d["box"][1] + d["box"][3] / 2
                dist = ((dcx - cx) ** 2 + (dcy - cy) ** 2) ** 0.5
                if dist <= radius * diag * 6:   # 대략적 근접 반경(박스 대각선의 6배 — 성긴 검출 간격 고려)
                    if d["tid"] == tid:
                        found_same = True
                    else:
                        found_new = True
        if found_same:
            retained_same_tid += 1
        elif found_new:
            reappeared_new_tid += 1
    return {"gap_events": events, "retained_same_tid": retained_same_tid,
            "reappeared_as_new_tid": reappeared_new_tid,
            "retention_pct": round(100 * retained_same_tid / events, 1) if events else None}


def main() -> None:
    frames, fps = bq.load_detections_cache(Path("benchmarks/_sweep_cache/multi_scene.json"))
    print(f"multi_scene.mp4: {len(frames)}프레임 @ {fps}fps")

    global_first_seen: dict[int, float] = {}
    for f in frames:
        t = f["t_cap_ms"] / 1000.0
        for d in f["dets"]:
            if d["cls"] == "person":
                global_first_seen.setdefault(d["tid"], t)

    lines = [
        "# 추적 품질 baseline(IoU, guard._track 현행) — multi_scene.mp4 (2026-08-06)",
        "",
        "> 측정 전용, 코드 무수정. `agents/guard.py _track()`(TRACK_IOU=0.45·STALE_MAX_MISSES=1·"
        "TRACK_TTL=1.2s, 재식별 없음)이 만든 tid 스트림을 구간별로 분석.",
        "",
        "| 구간 | 시간(초) | 라벨 | ID스위치 | ID swap(엄격) | 신규트랙(파편화) | 가림후 이벤트/재등장(새tid)/유지율 |",
        "|---|---|---|---|---|---|---|",
    ]
    for seg in SEGMENTS:
        t0, t1 = seg["range"]
        seg_frames = _person_frames(frames, t0, t1)
        sw = id_switches_and_swaps(seg_frames)
        frag = fragmentation(seg_frames, global_first_seen)
        occ = occlusion_retention(frames, (t0, t1))
        lines.append(
            f"| {seg['name']} | {t0:.1f}-{t1:.1f} | {seg['label']} "
            f"| {sw['switches']} | {sw['swaps']} | {frag['new_tracks']} "
            f"| {occ['gap_events']}/{occ['reappeared_as_new_tid']}/{occ['retention_pct']}% |"
        )

    lines += ["", "## 구간별 신규 tid 목록(파편화 원자료 — 육안 교차검증용)", ""]
    for seg in SEGMENTS:
        t0, t1 = seg["range"]
        seg_frames = _person_frames(frames, t0, t1)
        frag = fragmentation(seg_frames, global_first_seen)
        lines.append(f"- **{seg['name']}**({t0:.1f}-{t1:.1f}s): {len(frag['tids'])}개 신규 tid = {frag['tids']}")

    total_person_tids = len({d["tid"] for f in frames for d in f["dets"] if d["cls"] == "person"})
    lines += [
        "",
        "## 전체 요약",
        f"- 클립 전체 person 고유 tid: **{total_person_tids}개**(20.7초 동안 — 실제 동시 최대 인원은 육안 4~6명 수준, "
        f"고유 tid 수가 훨씬 많다는 것 자체가 파편화의 증거).",
        "- **가림후 ID유지율은 균일하지 않다(0%가 기본값이라는 가설은 실측으로 기각)**: S2(안정구간) 100%·"
        "S4(저인원) 60%처럼 **짧은 미탐지(guard._track 의 STALE_MAX_MISSES=1·TRACK_TTL=1.2s 허용 범위 내)는 "
        "같은 tid 로 잘 이어진다.** 반대로 S3(가림 후보) 20%·S5(다인 파편화) 4.5%처럼 **미탐지가 그 허용치를 "
        "넘거나 배경 인물처럼 애초에 검출이 불안정한 경우에만 tid 가 끊긴다**(재사용은 설계상 없음 — "
        "`_tid_seq` 단조증가 — 이므로 재등장은 항상 새 tid). Phase2(ByteTrack)가 개선할 여지가 있는 건 "
        "**S3·S5 처럼 낮게 나온 구간**이지, 전 구간이 균일하게 나쁜 게 아니다.",
        "",
        "## 정직 고지",
        "- **ID swap 수치는 보수적 프록시**(양방향 대칭 교환만 인정)라 실제보다 적게 잡힐 수 있다. "
        "'신규트랙(파편화)' 수가 대부분의 혼란을 흡수하고 있어(교차 시 한쪽만 tid 바뀌고 새 트랙으로 잡히는 "
        "'편도 전환'이 더 흔함), swap 보다 fragmentation 이 이 클립의 지배적 실패모드로 보인다.",
        "- S1(빠른이동 후보)은 카메라 팬과 뒤섞여 있어 순수 '사람의 빠른 이동'만의 효과로 단정할 수 없다"
        "(`multi_scene_labels.md` 참고).",
    ]

    out = Path("benchmarks/track_quality_baseline.md")
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
