#!/usr/bin/env python3
"""[V1-보완] pose 스핀 대기 실재 여부 판정 — onnxruntime 세션 옵션만 바꿔 같은 부하를 재측정.

가설: RTMPose 의 CPU 소모(1명·2Hz 에서 ~0.9코어)는 **실연산(7.5ms/호출)이 아니라
onnxruntime 스레드풀의 스핀(busy-wait)** 이 지배한다.

근거가 된 관측(v1_pose.json): 호출 빈도를 0.2→2→10Hz 로 바꿔도 **호출당 CPU 가 ~43%·s 로
일정**했고 지연은 7.5ms 로 변하지 않았다.

실험: `rtmlib/tools/base.py:80` 이 `ort.InferenceSession(..., providers=[...])` 만 넘기고
**SessionOptions 를 안 준다**(= ORT 기본값: intra_op 스레드 = 코어 수, 스핀 켜짐).
같은 모델 파일로 세션만 다시 만들어 옵션을 바꾸고 동일 부하를 잰다.

★서비스 코드는 건드리지 않는다. 이 프로세스 안에서만 세션을 교체한다(측정 전용).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "D:/vigent_original/vigent-core")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402


def pct(v: list[float], q: float) -> float | None:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * q))], 1) if v else None


def find_sessions(obj, seen=None, depth=0):
    """rtmlib Body 안의 BaseTool 인스턴스(.session + .onnx_model)를 재귀로 찾는다."""
    if seen is None:
        seen = set()
    if depth > 4 or id(obj) in seen:
        return []
    seen.add(id(obj))
    found = []
    if hasattr(obj, "session") and hasattr(obj, "onnx_model"):
        found.append(obj)
    for name in dir(obj):
        if name.startswith("__"):
            continue
        try:
            v = getattr(obj, name)
        except Exception:
            continue
        # ★rtmlib 의 YOLOX·RTMPose 는 __call__ 을 정의해 callable 이다 —
        #   callable 을 걸러내면 세션을 못 찾는다(첫 시도 실패 원인).
        if hasattr(v, "__dict__"):
            found += find_sessions(v, seen, depth + 1)
    return found


def retune(tools, intra_threads: int, allow_spin: bool):
    """같은 .onnx 파일로 세션을 다시 만들되 SessionOptions 만 바꾼다."""
    import onnxruntime as ort
    for t in tools:
        so = ort.SessionOptions()
        so.intra_op_num_threads = intra_threads
        so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "1" if allow_spin else "0")
        t.session = ort.InferenceSession(path_or_bytes=t.onnx_model, sess_options=so,
                                         providers=["CPUExecutionProvider"])


def measure(det, frames, boxes, rate: float, secs: float) -> dict:
    proc = psutil.Process()
    psutil.cpu_percent(percpu=True)
    proc.cpu_percent()
    lat: list[float] = []
    t_begin = time.time()
    t_end = t_begin + secs
    nxt = time.time()
    i = 0
    while time.time() < t_end:
        now = time.time()
        if now < nxt:
            time.sleep(min(0.02, nxt - now))
            continue
        nxt = now + 1.0 / rate
        t0 = time.time()
        det.persons(frames[i % len(frames)], bboxes=boxes)
        lat.append((time.time() - t0) * 1000)
        i += 1
    pcpu = round(proc.cpu_percent(), 1)
    return {"rate_hz": rate, "calls": len(lat), "t_start": t_begin, "t_end": time.time(),
            "lat_p50": pct(lat, .5), "lat_p95": pct(lat, .95),
            "proc_cpu_pct": pcpu, "cores": round(pcpu / 100.0, 2),
            "cpu_per_call_pct_s": round(pcpu / rate, 1) if rate else None}


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    rate = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    frames = []
    for v in sorted(Path("D:/vigent_original/runs/rfdetr/accident").glob("*.mp4"))[:3]:
        cap = cv2.VideoCapture(str(v))
        for _ in range(20):
            ok, f = cap.read()
            if ok:
                frames.append(f)
        cap.release()

    from pose.rtmpose_adapter import RtmPoseDetector
    det = RtmPoseDetector()
    h, w = frames[0].shape[:2]
    bw, bh = w * 0.18, h * 0.7
    boxes = [[w / 2 - bw / 2, h * 0.15, w / 2 + bw / 2, h * 0.85]]   # 사람 1명
    det.persons(frames[0], bboxes=boxes)                             # 예열

    tools = find_sessions(det)
    print(f"발견한 ORT 세션 {len(tools)}개: {[Path(str(t.onnx_model)).name for t in tools]}", flush=True)
    if not tools:
        print("★세션을 못 찾음 — 실험 불가")
        return 1

    results = []
    # ① 기준선(ORT 기본값 그대로 — rtmlib 이 만든 세션)
    r = measure(det, frames, boxes, rate, secs)
    r["arm"] = "기본값(rtmlib 그대로)"
    results.append(r)
    print(f"  [기본값] 지연 p50 {r['lat_p50']}ms · CPU {r['proc_cpu_pct']}% ({r['cores']}코어) · "
          f"호출당 {r['cpu_per_call_pct_s']}%·s", flush=True)

    # ②③④ 옵션 변경 대조군
    for label, threads, spin in [("스핀OFF·4스레드", 4, False),
                                 ("스핀OFF·2스레드", 2, False),
                                 ("스핀OFF·1스레드", 1, False)]:
        retune(tools, threads, spin)
        det.persons(frames[0], bboxes=boxes)     # 재예열
        time.sleep(1.0)
        r = measure(det, frames, boxes, rate, secs)
        r["arm"] = label
        results.append(r)
        print(f"  [{label}] 지연 p50 {r['lat_p50']}ms · CPU {r['proc_cpu_pct']}% ({r['cores']}코어) · "
              f"호출당 {r['cpu_per_call_pct_s']}%·s", flush=True)

    base = results[0]
    best = min(results[1:], key=lambda x: x["proc_cpu_pct"])
    saved = round((base["proc_cpu_pct"] - best["proc_cpu_pct"]) / 100.0, 2)
    verdict = "스핀 낭비 실재" if saved >= 0.20 else "스핀 낭비 미확인"
    print(f"★판정: {verdict} — 기본 {base['cores']}코어 → 최선({best['arm']}) {best['cores']}코어, "
          f"카메라당 회복량 {saved}코어 (지연 {base['lat_p50']}→{best['lat_p50']}ms)", flush=True)
    Path("v1_pose_spin.json").write_text(
        json.dumps({"verdict": verdict, "cores_recovered": saved, "rows": results},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
