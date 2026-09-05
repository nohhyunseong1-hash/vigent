#!/usr/bin/env python3
"""[V1-보완] RTMPose(근골격 자세) CPU 비용 실측.

★중요: RTMPose 는 이미 **CPU(onnxruntime)** 로 돈다(`pose/rtmpose_adapter.py:22`,
device="cpu"·backend="onnxruntime"). 따라서 GPU 를 빼도 이 비용은 그대로다 —
GPU-less 판정에서 같은 CPU 를 나눠 쓰는 항목이라 반드시 따로 세어야 한다.

실행 조건은 워커와 맞춘다:
  - 호출 빈도: `worker.pose_fps`(기본 2.0) 와 `ErgonomicsTracker._MIN_INTERVAL`(0.5초)
    중 느린 쪽 → 초당 2회
  - 입력: guard person 박스(top-down). 사람 수에 비례하므로 1·2·3명으로 나눠 잰다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]   # [C5] 절대경로 제거
sys.path.insert(0, str(_REPO / "vigent-core"))
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402


def pct(v: list[float], q: float) -> float | None:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * q))], 1) if v else None


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 45.0
    rates = [float(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["2"])]
    people_list = [int(x) for x in (sys.argv[3].split(",") if len(sys.argv) > 3 else ["1","2","3"])]
    vids = sorted(media("runs/rfdetr/accident").glob("*.mp4"))[:3]

    # 실제 프레임 확보(디코드 비용을 측정에서 빼기 위해 미리 메모리에 올린다)
    frames: list[np.ndarray] = []
    for v in vids:
        cap = cv2.VideoCapture(str(v))
        for _ in range(20):
            ok, f = cap.read()
            if ok:
                frames.append(f)
        cap.release()
    if not frames:
        print("프레임 확보 실패")
        return 1

    from pose.rtmpose_adapter import RtmPoseDetector
    det = RtmPoseDetector()

    h, w = frames[0].shape[:2]
    # 합성 사람 박스(프레임 중앙부 세로 박스) — 실제 person 박스 형태에 맞춘 top-down 입력
    def boxes_for(n: int) -> list[list[float]]:
        out = []
        for i in range(n):
            cx = w * (i + 1) / (n + 1)
            bw, bh = w * 0.18, h * 0.7
            out.append([max(0, cx - bw / 2), h * 0.15, min(w, cx + bw / 2), h * 0.85])
        return out

    det.persons(frames[0], bboxes=boxes_for(1))          # 예열(모델 최초 로드)
    time.sleep(1.0)

    results = []
    for rate in rates:
     for n_people in people_list:
        bx = boxes_for(n_people)
        proc = psutil.Process()
        psutil.cpu_percent(percpu=True)
        proc.cpu_percent()
        lat: list[float] = []
        t_end = time.time() + secs
        i = 0
        nxt = time.time()
        while time.time() < t_end:
            now = time.time()
            if now < nxt:
                time.sleep(min(0.02, nxt - now))
                continue
            nxt = now + 1.0 / rate                # 호출 빈도(초당 rate 회)
            t0 = time.time()
            det.persons(frames[i % len(frames)], bboxes=bx)
            lat.append((time.time() - t0) * 1000)
            i += 1
        cores = psutil.cpu_percent(percpu=True)
        pcpu = round(proc.cpu_percent(), 1)
        r = {"rate_hz": rate, "people": n_people, "calls": len(lat),
             "lat_p50": pct(lat, .5), "lat_p95": pct(lat, .95),
             "proc_cpu_pct": pcpu, "cores": round(pcpu / 100.0, 2),
             "core_mean": round(sum(cores) / len(cores), 1)}
        results.append(r)
        print(f"  [pose] {rate}Hz 사람 {n_people}명: 지연 p50 {r['lat_p50']} p95 {r['lat_p95']}ms · "
              f"프로세스 CPU {pcpu}% ({r['cores']}코어) · 호출 {len(lat)}회", flush=True)

    Path("v1_pose.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
