"""RTSP(IP카메라) 연결 테스트 — Tapo C200 등에서 영상이 실제로 오는지 확인.

VIGENT 본체에 붙이기 전, 카메라 주소·계정이 맞는지 먼저 검증하는 도구(기존 기능 무영향).
비밀번호 노출 방지: 주소는 .env 의 RTSP_URL 에서 읽거나 인자로 전달.

사용:
  # 1) .env 에 RTSP_URL=rtsp://계정:비번@192.168.0.10:554/stream1 넣고:
  python tools/rtsp_test.py
  # 2) 또는 직접:
  python tools/rtsp_test.py "rtsp://계정:비번@192.168.0.10:554/stream1"
출력: 연결 성공/실패 진단 + 첫 프레임을 runs/rtsp/first_frame.jpg 로 저장
※ 2026-09-06 감사: vigent-core/ml/ → tools/ 이동(ROOT 계산 한 단계 얕아짐).
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_url() -> str | None:
    if len(sys.argv) > 1 and sys.argv[1].startswith("rtsp://"):
        return sys.argv[1]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("RTSP_URL"):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    return None


def mask(url: str) -> str:
    """로그에 비번 가리기."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)


def main() -> None:
    url = load_url()
    if not url:
        print("❌ RTSP 주소가 없습니다.")
        print("   방법1) .env 에  RTSP_URL=rtsp://계정:비번@카메라IP:554/stream1  추가")
        print("   방법2) python tools/rtsp_test.py \"rtsp://...\"")
        return

    import cv2
    print(f"[rtsp] 연결 시도: {mask(url)}")
    # FFMPEG 백엔드 + TCP 강제(불안정 네트워크에서 더 안정)
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    t0 = time.time()
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print(f"❌ 연결 실패({time.time()-t0:.1f}s). 점검:")
        print("   · 카메라와 이 컴퓨터가 같은 와이파이인가")
        print("   · 카메라 IP / 계정ID / 비밀번호가 맞는가(Tapo앱 → 카메라계정)")
        print("   · 끝이 /stream1(고화질) 또는 /stream2(저화질) 인가")
        return

    # 첫 프레임 받기(최대 10초 시도)
    ok, frame = False, None
    for _ in range(50):
        ok, frame = cap.read()
        if ok and frame is not None:
            break
        time.sleep(0.2)
    if not ok or frame is None:
        print("❌ 연결은 됐으나 영상 프레임을 못 받음(스트림 경로/화질 확인)")
        cap.release()
        return

    h, w = frame.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS)
    out_dir = ROOT / "runs" / "rtsp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "first_frame.jpg"
    cv2.imwrite(str(out), frame)
    cap.release()

    print(f"✅ 연결 성공! 해상도 {w}x{h} · {fps:.0f}fps · 연결 {time.time()-t0:.1f}s")
    print(f"   첫 프레임 저장: {out.relative_to(ROOT)} (열어서 카메라 화면 맞는지 확인)")
    print("   → 다음: VIGENT 파이프라인에 이 주소를 연결할 수 있습니다.")


if __name__ == "__main__":
    main()
