#!/usr/bin/env python3
"""F-8 추적 품질 측정·A/B (item4) — SORT vs ByteTrack vs OCSORT vs BoTSORT.

공정 비교: RF-DETR 사람검출을 **프레임당 1회만** 돌려 캐시 → 동일 검출을 각 추적기에 통과시켜
추적기만 변수로 둔다. GT 트랙ID 가 없으므로(라벨 대기) **상대 비교용 프록시 지표**를 낸다:
  · unique_ids      : 부여된 고유 트랙ID 수 (실사람보다 많으면 단편화/스위치)
  · id_switches     : 연속 프레임 IoU 매칭 시 같은 물체의 ID 가 바뀐 횟수(낮을수록 좋음)
  · frag(단편화)    : unique_ids / 추정 물체수(최대 동시 person) (1에 가까울수록 좋음)
  · track_len       : ID별 지속 프레임 수 mean/median, 단명(<3f) 트랙 수
검출은 4개 추적기에 동일 입력 → 검출 성능 차이는 배제, 순수 추적 안정성만 비교.

사용:
  python3 tools/track_quality.py --video runs/rfdetr/test_walk.mp4 --tag walk
  python3 tools/track_quality.py --video "footage/크레인 재해.MP4" --max-frames 300 --tag crane
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))


def _args():
    p = argparse.ArgumentParser(description="F-8 추적 품질 A/B")
    p.add_argument("--video", required=True, help="입력 영상 경로")
    p.add_argument("--max-frames", type=int, default=0, help="처리 프레임 상한(0=전체)")
    p.add_argument("--threshold", type=float, default=0.4, help="검출 임계. 기본 0.4")
    p.add_argument("--trackers", default="SORTTracker,ByteTrackTracker,OCSORTTracker,BoTSORTTracker")
    p.add_argument("--report-dir", default=str(_ROOT / "audit"))
    p.add_argument("--tag", default="")
    return p.parse_args()


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _detect_all(video, max_frames, thr):
    """RF-DETR 사람검출을 프레임당 1회 → [(xyxy[Nx4], conf[N])] 캐시."""
    import cv2
    import device as _device
    import numpy as np
    from PIL import Image
    from rfdetr import RFDETRNano
    from rfdetr.util.coco_classes import COCO_CLASSES
    dev = _device.pick_device(prefer_mps=True)
    model = RFDETRNano(device=dev)
    try:
        model.optimize_for_inference()
    except Exception:  # noqa: BLE001
        pass
    cap = cv2.VideoCapture(video)
    frames = []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok or (max_frames and i >= max_frames):
            break
        det = model.predict(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)), threshold=thr)
        xyxy, conf = [], []
        for j in range(len(det)):
            if COCO_CLASSES[det.class_id[j]] != "person":
                continue
            xyxy.append([float(v) for v in det.xyxy[j]])
            conf.append(float(det.confidence[j]))
        frames.append((np.array(xyxy, dtype=float).reshape(-1, 4), np.array(conf, dtype=float)))
        i += 1
    cap.release()
    return frames, dev


def _run_tracker(name, frames):
    """캐시된 검출을 한 추적기에 통과 → 프레임별 [(track_id, xyxy)] 목록."""
    import numpy as np
    import supervision as sv
    import trackers as T
    tracker = getattr(T, name)()
    per_frame = []
    for xyxy, conf in frames:
        if len(xyxy) == 0:
            det = sv.Detections.empty()
        else:
            det = sv.Detections(xyxy=xyxy.copy(), confidence=conf.copy(),
                                class_id=np.zeros(len(xyxy), dtype=int))
        try:
            det = tracker.update(det)
        except Exception:  # noqa: BLE001
            pass
        tids = getattr(det, "tracker_id", None)
        rows = []
        for k in range(len(det)):
            tid = int(tids[k]) if (tids is not None and tids[k] is not None) else -1
            rows.append((tid, [float(v) for v in det.xyxy[k]]))
        per_frame.append(rows)
    return per_frame


def _metrics(per_frame):
    """프록시 지표 계산."""
    from collections import defaultdict
    id_frames = defaultdict(int)
    for rows in per_frame:
        for tid, _ in rows:
            if tid >= 0:
                id_frames[tid] += 1
    unique_ids = len(id_frames)
    max_simul = max((sum(1 for tid, _ in rows if tid >= 0) for rows in per_frame), default=0)
    lens = sorted(id_frames.values())
    mean_len = sum(lens) / len(lens) if lens else 0.0
    med_len = lens[len(lens) // 2] if lens else 0.0
    short = sum(1 for x in lens if x < 3)
    # ID 스위치: 연속 프레임 IoU>0.5 매칭 시 ID 변경 횟수
    switches = 0
    for a, b in zip(per_frame, per_frame[1:]):
        for tid_b, box_b in b:
            if tid_b < 0:
                continue
            best, best_tid = 0.0, None
            for tid_a, box_a in a:
                if tid_a < 0:
                    continue
                v = _iou(box_a, box_b)
                if v > best:
                    best, best_tid = v, tid_a
            if best >= 0.5 and best_tid is not None and best_tid != tid_b:
                switches += 1
    frag = (unique_ids / max_simul) if max_simul else 0.0
    return {"unique_ids": unique_ids, "id_switches": switches, "max_simul": max_simul,
            "frag": round(frag, 2), "mean_len": round(mean_len, 1), "med_len": med_len,
            "short_tracks": short}


def main():
    a = _args()
    from datetime import datetime
    print(f"[track] 검출 캐시 생성(RF-DETR, 1회): {a.video}", flush=True)
    frames, dev = _detect_all(a.video, a.max_frames, a.threshold)
    n = len(frames)
    total_det = sum(len(x) for x, _ in frames)
    print(f"[track] {n}프레임 · person 검출 총 {total_det}개 · device={dev}", flush=True)

    results = {}
    for name in [t.strip() for t in a.trackers.split(",") if t.strip()]:
        print(f"[track] 추적기 실행: {name}", flush=True)
        try:
            pf = _run_tracker(name, frames)
            results[name] = _metrics(pf)
        except Exception as e:  # noqa: BLE001
            results[name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"[track]   실패: {results[name]['error']}", flush=True)

    # 리포트
    Path(a.report_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    base = Path(a.report_dir) / f"track_quality_{stamp}{('_'+a.tag) if a.tag else ''}"
    L = [f"# F-8 추적 품질 A/B — {stamp}{(' / '+a.tag) if a.tag else ''}", "",
         f"> 영상 `{a.video}` · {n}프레임 · person 검출 {total_det}개(동일 입력) · 임계 {a.threshold} · device {dev}",
         "> GT 트랙ID 없음 → **상대 비교용 프록시 지표**(라벨 확보 시 MOTA/IDF1 로 대체).", "",
         "| 추적기 | 고유ID | ID스위치 | 단편화(ID/최대동시) | 트랙길이 mean/med | 단명(<3f) |",
         "|---|---|---|---|---|---|"]
    for name, m in results.items():
        if "error" in m:
            L.append(f"| {name} | — | — | — | — | (오류: {m['error']}) |")
        else:
            L.append(f"| {name} | {m['unique_ids']} | **{m['id_switches']}** | "
                     f"{m['frag']} (max동시 {m['max_simul']}) | {m['mean_len']}/{m['med_len']} | {m['short_tracks']} |")
    L += ["", "## 해석",
          "- **ID스위치·단편화가 낮고 트랙길이가 길수록** 추적 안정(같은 사람=같은 ID 유지).",
          "- 고유ID가 최대동시 person 수에 가까울수록 좋음(과다=끊김/스위치).",
          "- 프록시 지표라 절대값보다 **추적기 간 상대 비교**가 유효. 최종 채택은 실영상·라벨로 재확인.",
          f"- 원자료 판단: 최소 스위치·최소 단편화 추적기를 후보로. 현행={list(results)[0] if results else '?'}."]
    base.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[track] 리포트: {base.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
