#!/usr/bin/env python3
"""benchmarks/rtsp_capture_probe.py — [CODE_REVIEW M5-1·M5-2] 캡처 전용 독립 실측(서버·워커·경보 미사용).

(1) 죽은 IP 연결 시도 → 실패까지 소요 시간을 FFmpeg 옵션 전/후로 비교(목표 30s → ≤5s).
(2) --live <camera_id> : data/camera_secrets.json 의 원본 주소로 10초 수신 프레임 수·None 비율·첫 프레임 지연을
    옵션 전/후 비교(자격증명은 출력하지 않는다). 카메라 사용 승인이 있을 때만 쓴다.
옵션 문자열은 각 시도마다 **새 프로세스**에서 적용한다(OPENCV_FFMPEG_CAPTURE_OPTIONS 는 첫 VideoCapture 생성 전에
읽히므로 같은 프로세스 안에서 바꿔 재측정하면 안 된다 — 이 스크립트가 자기 자신을 subprocess 로 부른다).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

OLD = "rtsp_transport;tcp|max_delay;500000"                                        # 수정 전(worker.py:64)
# 수정 후 = worker._FFMPEG_CAPTURE_OPTIONS 와 동일(타임아웃은 FFmpeg 옵션이 아니라 OpenCV 속성으로 건다).
# ★[5단계 마무리 실측, 2026-09-06] 예전 NEW 에 있던 `timeout;5000000` 은 cv2 4.13 휠의 FFmpeg 4.4(avformat 58.76)가
#   모르는 옵션이라 VideoCapture 가 **0.02s 만에 "can't create capture"** — 죽은 IP 뿐 아니라 살아 있는 카메라도 못 연다.
#   (cv2 5.0/FFmpeg 7.1 에서는 무시돼 98.8s.) 앱(worker.py)은 이 옵션을 쓰지 않으며, 4.13 재검증: 옵션만 30.1s ·
#   옵션+OpenCV 속성(앱 경로) **5.05s** · 구 옵션+속성 5.05s.
NEW = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000"


def _mask(u: str) -> str:
    import re
    return re.sub(r"(\w+://)([^/@]+)@", r"\1***:***@", u)


PROPS_MS = 5000     # OpenCV 자체 타임아웃(CAP_PROP_OPEN_TIMEOUT_MSEC / READ_TIMEOUT_MSEC) — FFmpeg 옵션 이름과 무관


def _child(opts: str, url: str, seconds: float, props: bool = False) -> dict:
    env = dict(os.environ)
    env["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
    env["PYTHONUTF8"] = "1"
    try:
        r = subprocess.run([sys.executable, __file__, "--_child", url, str(seconds), "1" if props else "0"],
                           capture_output=True, text=True, env=env, timeout=400)
    except subprocess.TimeoutExpired:
        return {"error": "child timeout 400s"}
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    return json.loads(line[-1]) if line else {"error": r.stderr[-300:]}


def _measure(url: str, seconds: float, props: bool = False) -> dict:
    import cv2
    t0 = time.time()
    if props:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                               [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, PROPS_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, PROPS_MS])
    else:
        cap = cv2.VideoCapture(url)
    t_open = time.time() - t0
    opened = bool(cap.isOpened())
    frames = nones = 0
    first = None
    t1 = time.time()
    while time.time() - t1 < seconds and opened:
        ok, fr = cap.read()
        if ok and fr is not None:
            frames += 1
            if first is None:
                first = time.time() - t0
        else:
            nones += 1
            if not opened or nones > 50 and frames == 0:
                break
    t_total = time.time() - t0
    cap.release()
    return {"opened": opened, "open_s": round(t_open, 2), "total_s": round(t_total, 2), "frames": frames,
            "nones": nones, "none_ratio": round(nones / max(1, frames + nones), 3),
            "first_frame_s": round(first, 2) if first is not None else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--_child", nargs=3, metavar=("URL", "SEC", "PROPS"))
    ap.add_argument("--dead-ip", default="192.168.0.251")
    ap.add_argument("--live", default="", help="data/camera_secrets.json 의 카메라 id(승인 시)")
    ap.add_argument("--seconds", type=float, default=10.0)
    ns = ap.parse_args()
    if ns._child:
        print(json.dumps(_measure(ns._child[0], float(ns._child[1]), ns._child[2] == "1")))
        return
    dead = f"rtsp://{ns.dead_ip}:554/stream1"
    print(f"cv2 FFmpeg 옵션 A/B — 죽은 IP {ns.dead_ip}", flush=True)
    print("| 케이스 | 옵션 | opened | 실패까지 s |")
    print("|---|---|---|---|", flush=True)
    for label, opts, props in (("구", OLD, False), ("신(FFmpeg timeout 옵션)", NEW, False),
                               ("신+OpenCV 타임아웃 prop", NEW, True)):
        r = _child(opts, dead, 2.0, props)
        print(f"| 죽은 IP | {label} | {r.get('opened')} | {r.get('total_s', r.get('error'))} |", flush=True)
    if ns.live:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vigent-core"))
        import camera_registry
        url = camera_registry.source_of(ns.live) or ""
        print(f"\n실카메라 {ns.live} ({_mask(url)}) — {ns.seconds:.0f}s 수신")
        print("| 옵션 | opened | 첫 프레임 s | 프레임 수 | None | None 비율 |")
        print("|---|---|---|---|---|---|")
        for label, opts, props in (("구", OLD, False), ("신", NEW, False), ("신+prop", NEW, True)):
            r = _child(opts, url, ns.seconds, props)
            print(f"| {label} | {r.get('opened')} | {r.get('first_frame_s')} | {r.get('frames')} | {r.get('nones')} | {r.get('none_ratio')} |")


if __name__ == "__main__":
    main()
