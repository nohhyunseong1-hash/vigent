"""pose_e2e.py — 포즈 판정층(출력층) 검증 하네스 (T10c-V, FINDINGS F-4 해소용).

사용자 촬영 클립을 production 경로 그대로 순회 실행:
    프레임 → guard.detect(person 박스) → RTMPose(top-down) → ErgonomicsTracker.
판정 로직(ErgonomicsTracker·ergonomics.py)은 '재사용(무수정)'. 이 하네스는 관찰만 한다.
(작업자 낙상 판정 제거 — P3_BACKLOG 참조. 이 하네스도 ergo 전용으로 축소.)

입력:
  benchmarks/data/pose_clips/*.mp4(.mov/.avi)  +  labels.json
  labels.json: { "<파일명>": {"tag":"ergo|multi",
                              "ergo_expected": "good|warn|bad|null"} }
출력:
  benchmarks/results/pose_e2e.json — 클립별 (ergo 등급 시계열·플리커, 인원수)
  게이트: 부담자세 기대등급 일치. 다인은 게이트 아님(관찰).

실행: /opt/anaconda3/bin/python3 benchmarks/pose_e2e.py [--fps 2.0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import ergonomics as _erg          # noqa: E402  등급 시계열용(판정 함수 재사용)
import worker as W                  # noqa: E402  production ErgonomicsTracker/_posemodel

_CLIPS = _ROOT / "benchmarks" / "data" / "pose_clips"
_OUT = _ROOT / "benchmarks" / "results" / "pose_e2e.json"


def _guard():
    global _G
    if "_G" not in globals():
        import main as M
        b = M.STATE.get(M.DEFAULT_THEME) or M._load_theme(M.DEFAULT_THEME)
        _G = b["agents"]["Guard"]
    return _G


def _person_boxes(frame):
    """production 과 동일: guard.detect(person) 박스(픽셀, _nms/_track 적용)."""
    g = _guard()
    g._tracks = []                       # 클립 내에서도 프레임 독립 검출(추적은 트래커가 담당)
    h, w = frame.shape[:2]
    out = g.detect(frame, detectors=["person"])
    return [[d["bbox"][0] * w, d["bbox"][1] * h, d["bbox"][2] * w, d["bbox"][3] * h]
            for d in out.get("detections", []) if d["label"] == "person"]


def _frame_grade(frame, boxes, joints):
    """이 프레임의 사람들 유효 ergo 등급 최댓값(none<good<warn<bad) — 시계열/플리커용.
    ErgonomicsTracker 와 동일한 assess+effective_worst 재사용(무수정)."""
    persons = W._posemodel.persons(frame, boxes)
    rank = {"none": 0, "good": 1, "warn": 2, "bad": 3}
    worst, worst_r = "none", 0
    for p in persons:
        a = _erg.assess(p["kp_xy"], p["kp_cf"], joints)
        g = _erg.effective_worst(a.get("grades", {})) if a else "none"
        if rank.get(g, 0) > worst_r:
            worst, worst_r = g, rank[g]
    return worst, len(persons)


def _run_clip(path, fps, joints):
    etrack = W.ErgonomicsTracker()
    cap = cv2.VideoCapture(str(path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / fps)))    # 워커 fps 로 서브샘플(production 시간축 재현)
    ergo_fired, grade_series, persons_series = [], [], []
    fi = idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if fi % step == 0:
            ts = idx / fps                       # 균등 타임스탬프(트래커 시간로직 정상 동작)
            boxes = _person_boxes(frame)
            try:
                ef = etrack.update(frame, ts, boxes)
            except Exception:  # noqa: BLE001
                ef = []
            grade, npeople = _frame_grade(frame, boxes, joints)
            for rule, level, note in ef:
                ergo_fired.append({"frame": idx, "level": level})
            grade_series.append(grade)
            persons_series.append(npeople)
            idx += 1
        fi += 1
    cap.release()
    # 등급 플리커(good↔warn 인접 전이 횟수) — F-2 실증
    flicker = sum(1 for a, b in zip(grade_series, grade_series[1:])
                  if {a, b} == {"good", "warn"})
    from collections import Counter
    return {
        "sampled_frames": idx, "src_fps": round(src_fps, 1), "sample_fps": fps,
        "ergo_fired": ergo_fired,
        "ergo_grade_counts": dict(Counter(grade_series)),
        "ergo_grade_worst": max(grade_series, key=lambda g: {"none": 0, "good": 1, "warn": 2, "bad": 3}[g])
        if grade_series else "none",
        "ergo_flicker_good_warn": flicker,
        "persons_max": max(persons_series, default=0),
        "persons_avg": round(sum(persons_series) / len(persons_series), 2) if persons_series else 0,
    }


def _gate(tag, exp, r):
    """클립별 게이트 판정(다인=관찰). 반환 (판정문자열, 통과여부|None)."""
    if tag == "ergo":
        ok = (exp is None) or (r["ergo_grade_worst"] == exp)
        return (f"등급 {r['ergo_grade_worst']} vs 기대 {exp} " + ("일치" if ok else "불일치")), ok
    return "다인(관찰, 게이트 아님)", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=float, default=2.0, help="서브샘플 fps(워커 기본 2.0)")
    args = ap.parse_args()

    labels_path = _CLIPS / "labels.json"
    clips = sorted([p for p in _CLIPS.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".avi", ".webm")]) \
        if _CLIPS.exists() else []
    if not clips:
        print(f"[대기] 클립 없음 — {_CLIPS.relative_to(_ROOT)}/ 에 영상 + labels.json 등록 후 재실행.")
        print("  labels.json 예: {\"ergo_01.mp4\": {\"tag\":\"ergo\",\"ergo_expected\":\"warn\"}}")
        return
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    joints = (_erg.load_ergonomics("safety") or {}).get("joints", {}) or {}

    results, gate_rows = {}, []
    for p in clips:
        lab = labels.get(p.name, {})
        tag = lab.get("tag", "ergo")
        r = _run_clip(p, args.fps, joints)
        verdict, passed = _gate(tag, lab.get("ergo_expected"), r)
        r["tag"], r["expected"] = tag, lab
        r["gate"] = {"verdict": verdict, "passed": passed}
        results[p.name] = r
        gate_rows.append((p.name, tag, verdict, passed))
        print(f"  {p.name:28} [{tag:8}] {verdict}  "
              f"(ergo_worst={r['ergo_grade_worst']}, flicker={r['ergo_flicker_good_warn']}, ppl~{r['persons_avg']})")

    # 게이트 집계
    ergo_clips = [g for g in gate_rows if g[1] == "ergo"]
    summary = {
        "ergo_gate": f"{sum(1 for g in ergo_clips if g[3])}/{len(ergo_clips)} 등급일치",
        "multi_clips": sum(1 for g in gate_rows if g[1] == "multi"),
    }
    _OUT.write_text(json.dumps({"summary": summary, "clips": results}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("\n=== 게이트 집계 ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"  → 저장: {_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
