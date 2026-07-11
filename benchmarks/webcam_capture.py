"""webcam_capture.py — 맥북 웹캠 자동 캡처 (VIGENT-MAX Phase 0).

장면 태그별 N장 자동 캡처 → data/datasets/webcam_bench/raw/<tag>_<연번>.jpg.
저장은 native 원본(JPEG q95) — webcam_bench 가 측정 시 640/JPEG0.72로 프론트 재현(측정=배포).
원본 보존은 negative 파인튜닝 재료로도 유리.

두 방식:
  대화형:  python3 benchmarks/webcam_capture.py           (태그·장수·간격 입력받음)
  인자:    python3 benchmarks/webcam_capture.py --tag neg_desk --count 10 --interval 1.0
  연번은 기존 <tag>_*.jpg 이어서 자동 부여. --countdown 으로 첫 캡처 전 대기(포즈용).
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RAW = _ROOT / "data/datasets/webcam_bench/raw"


def _next_index(tag: str) -> int:
    existing = sorted(_RAW.glob(f"{tag}_*.jpg"))
    mx = 0
    for p in existing:
        try:
            mx = max(mx, int(p.stem.rsplit("_", 1)[1]))
        except (ValueError, IndexError):
            pass
    return mx + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None, help="장면 태그(예: neg_desk, pos_hardhat_near)")
    ap.add_argument("--count", type=int, default=None, help="캡처 장수")
    ap.add_argument("--interval", type=float, default=1.2, help="캡처 간격(초)")
    ap.add_argument("--countdown", type=float, default=0.0, help="첫 캡처 전 대기(초, 포즈/자리비우기용)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--cam", type=int, default=0, help="카메라 인덱스")
    args = ap.parse_args()

    tag = args.tag or input("장면 태그(예 neg_desk / pos_hardhat_near): ").strip()
    count = args.count or int(input("캡처 장수(기본 10): ") or 10)
    interval = args.interval

    import cv2
    _RAW.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(args.cam)
    if not cap.isOpened():
        print("[오류] 웹캠 열기 실패 — 카메라 권한/점유 확인. 터미널에서 직접 '! python3 ...' 로 실행 시 권한 팝업 허용.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    # 웜업(자동노출·화이트밸런스 안정) — 초기 프레임 버림
    ok = False
    for _ in range(8):
        ok, frame = cap.read()
        time.sleep(0.08)
    if not ok or frame is None:
        print("[오류] 프레임 획득 실패(권한 거부 시 검은 프레임). 사용자 세션에서 '!' 실행 필요.")
        cap.release()
        return
    h, w = frame.shape[:2]
    print(f"  해상도 {w}x{h} · 태그 '{tag}' · {count}장 · 간격 {interval}s")

    if args.countdown > 0:
        print(f"  {args.countdown:.0f}초 후 시작 (자리 비우기/포즈)...")
        time.sleep(args.countdown)

    start = _next_index(tag)
    saved = []
    for i in range(count):
        ok, frame = cap.read()
        if not ok or frame is None:
            print(f"  [{i+1}/{count}] 프레임 실패, 건너뜀")
            continue
        idx = start + i
        fn = _RAW / f"{tag}_{idx:02d}.jpg"
        cv2.imwrite(str(fn), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        saved.append(fn.name)
        print(f"  [{i+1}/{count}] 저장 {fn.name}")
        if i < count - 1:
            time.sleep(interval)
    cap.release()
    print(f"\n완료: {len(saved)}장 → {_RAW}")
    print(f"  {saved[0] if saved else '-'} ~ {saved[-1] if saved else '-'}")


if __name__ == "__main__":
    main()
