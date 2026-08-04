#!/usr/bin/env python3
"""빠른 이동 벤치 클립 녹화 — 웹캠에서 10초 녹화해 runs/rfdetr/test_fast.mp4 저장.
사용: /opt/anaconda3/bin/python3 benchmarks/record_fast.py  (좌우로 빠르게 움직이며 녹화)
옵션: --seconds 10 --fps 15 --out runs/rfdetr/test_fast.mp4 --cam 0
※ 첫 실행 시 macOS 카메라 접근 허용 팝업 → 반드시 허용."""
import argparse
import time
from pathlib import Path

import cv2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--out", default="runs/rfdetr/test_fast.mp4")
    ap.add_argument("--cam", type=int, default=0)
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.cam)
    if not cap.isOpened():
        print("[오류] 카메라를 열 수 없음(권한/장치 확인)")
        return
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
    out_p = Path(a.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out_p), cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (w, h))

    print(f"● {a.seconds:.0f}초 녹화 시작 — 화면 좌우로 '빠르게' 움직이세요. ({w}x{h}@{a.fps:.0f})")
    print("  3초 후 시작...")
    t_warm = time.time()
    while time.time() - t_warm < 3:
        cap.read()
    n, t0, target = 0, time.time(), int(a.seconds * a.fps)
    while n < target:
        ok, fr = cap.read()
        if not ok:
            break
        vw.write(fr)
        n += 1
        if n % int(a.fps) == 0:
            print(f"  ...{n // int(a.fps)}s / {a.seconds:.0f}s")
    vw.release()
    cap.release()
    dt = time.time() - t0
    print(f"✅ 저장: {out_p}  ({n}프레임, {dt:.1f}s, 실효 {n/dt:.1f}fps)")
    print("이제 이 클립으로 수정 전/후 측정을 요청하세요.")


if __name__ == "__main__":
    main()
