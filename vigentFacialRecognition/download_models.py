"""download_models.py — OpenCV Zoo 공개 모델 내려받기 (상용 허용 라이선스)

검출 YuNet(MIT) + 인식 SFace(Apache-2.0). 둘 다 상업적 사용 가능.
새 파이썬 라이브러리 설치 없이 표준 라이브러리(urllib)만 사용.

사용:  python -m vigentFacialRecognition.download_models
"""
from __future__ import annotations

import sys
import urllib.request

from . import config

BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"
FILES = [
    (f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx", config.YUNET_PATH, "YuNet 검출 (MIT)"),
    (f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx", config.SFACE_PATH, "SFace 인식 (Apache-2.0)"),
]


def _hook(blocks, bs, total):
    if total > 0:
        pct = min(100, blocks * bs * 100 // total)
        sys.stdout.write(f"\r    {pct:3d}%")
        sys.stdout.flush()


def main() -> int:
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for url, dest, label in FILES:
        if dest.exists():
            print(f"[건너뜀] {label} — 이미 있음 ({dest.name})")
            continue
        print(f"[다운로드] {label}\n    {url}")
        try:
            urllib.request.urlretrieve(url, dest, _hook)
            print(f"\r    완료 → {dest}")
        except Exception as e:
            print(f"\n    실패: {e}")
            return 1
    print("\n모든 모델 준비 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
