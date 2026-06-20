"""테스트용 합성 영상 생성 — 사람 있는 이미지를 좌우로 이동시켜 '움직이는 사람' 영상으로.
외부 다운로드 없이 추적+위험구역 침입 파이프라인을 로컬에서 검증하기 위함.
사용: python3 vigent-core/ml/make_test_video.py <사람이미지> [출력.mp4]
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent


def main(img_path: str, out: str | None = None) -> None:
    out = out or str(ROOT / "runs" / "rfdetr" / "test_walk.mp4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    W, H = 960, 540                       # 출력 프레임 크기
    fps, n = 12, 48                       # 12fps, 4초
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    # 이미지를 H 높이에 맞춰 리사이즈한 뒤, 좌→우로 패닝(사람이 가로질러 가는 효과)
    scale = H / h
    rs = cv2.resize(img, (int(w * scale), H))
    rw = rs.shape[1]
    for i in range(n):
        # 0..(rw-W) 범위를 왕복하며 잘라낸다
        max_x = max(1, rw - W)
        x = int((np.sin(i / n * np.pi * 2) * 0.5 + 0.5) * max_x)
        frame = rs[:, x:x + W]
        if frame.shape[1] < W:            # 모자라면 패딩
            frame = cv2.copyMakeBorder(frame, 0, 0, 0, W - frame.shape[1], cv2.BORDER_REPLICATE)
        vw.write(frame)
    vw.release()
    print(f"✅ 테스트 영상 생성: {Path(out).relative_to(ROOT)} ({n}프레임/{fps}fps, {W}x{H})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python3 vigent-core/ml/make_test_video.py <사람이미지> [출력.mp4]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
