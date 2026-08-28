#!/usr/bin/env python3
"""[현장 원본 녹화] SD카드 없이 노트북이 RTSP 원본을 직접 mp4 로 저장한다.

배경(2026-08-27 학원 방문): C200 에 SD카드가 없어 원본 고화질 회수가 불가 →
카메라에 **두 번째 RTSP 연결**을 열어 노트북 디스크에 직접 녹화한다.
서버 판정 워커(첫 연결)와는 독립이라 검출·경보에 영향 없다(추론 없음, 디코드+저장만).

  · 화질: 카메라 원본(stream1 = 1080p·15fps) — overlay.mp4(1fps 스냅샷)와 달리 부드럽다
  · 자격증명: 서버 등록부에서 읽는다(화면 출력 안 함)
  · 파일: 10분 단위로 쪼개 저장 — 중간에 끊겨도 앞부분은 살아 있다
  · ⚠원본에는 얼굴 비식별화가 **없다**(스냅샷 경로만 모자이크) — 본인·동의자 촬영만.

사용:
  python scripts/rtsp_recorder.py --cam test               # STOP 파일 만들 때까지
  python scripts/rtsp_recorder.py --cam test --minutes 30
  종료: runs/raw_<날짜>/STOP 파일 생성(프로세스 kill 은 파일이 깨진다)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))


def main() -> int:
    import camera_registry as reg
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="test")
    ap.add_argument("--minutes", type=float, default=180.0, help="최대 길이(기본 3시간)")
    ap.add_argument("--segment-min", type=float, default=10.0, help="파일 분할 단위(분)")
    a = ap.parse_args()

    src = reg.source_of(a.cam)
    if not src:
        print(f"❌ 등록부에 {a.cam} 의 source 가 없다 — /cameras 로 id 확인")
        return 1

    out = ROOT / "runs" / f"raw_{time.strftime('%Y%m%d')}"
    out.mkdir(parents=True, exist_ok=True)
    stop = out / "STOP"
    if stop.exists():
        stop.unlink()

    cap = cv2.VideoCapture(src)
    ok, fr = cap.read()
    if not ok or fr is None:
        print("❌ RTSP 연결 실패 — 카메라 동시접속 한도이거나 주소 문제. 워커는 그대로 도는지 /health 확인.")
        return 1
    h, w = fr.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    if not (1.0 <= fps <= 60.0):
        fps = 15.0
    print(f"[원본 녹화 시작] {a.cam} — {w}x{h} @ {fps:.0f}fps · {a.segment_min:.0f}분 단위 분할")
    print(f"  저장: {out} · 종료: STOP 파일 생성")

    vw = None
    seg_t0 = t0 = time.time()
    n = seg_i = 0
    try:
        while time.time() - t0 < a.minutes * 60:
            if stop.exists():
                print("  STOP 감지 — 종료")
                break
            ok, fr = cap.read()
            if not ok or fr is None:
                print("  프레임 끊김 — 3초 후 재연결")
                cap.release()
                time.sleep(3)
                cap = cv2.VideoCapture(src)
                continue
            if vw is None or time.time() - seg_t0 >= a.segment_min * 60:
                if vw is not None:
                    vw.release()
                seg_i += 1
                seg_t0 = time.time()
                name = f"{a.cam}_{time.strftime('%H%M%S')}_{seg_i:02d}.mp4"
                vw = cv2.VideoWriter(str(out / name), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                print(f"  ▶ 새 파일: {name}")
            vw.write(fr)
            n += 1
            if n % int(fps * 60) == 0:
                print(f"  +{(time.time() - t0) / 60:.0f}분 · 프레임 {n}")
    finally:
        if vw is not None:
            vw.release()
        cap.release()
    print(f"[종료] {n}프레임 · {(time.time() - t0) / 60:.1f}분 · 파일 {seg_i}개 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
