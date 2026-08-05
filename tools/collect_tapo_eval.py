#!/usr/bin/env python3
"""tools/collect_tapo_eval.py — 실카메라 평가셋 수집(4.0 Phase 1).

test.1(Tapo) 등 등록 카메라 RTSP 에서 일정 간격 프레임을 저장한다. 도메인 차이(실카메라 시점·사물)로
인한 오탐을 측정·개선하기 위한 '현장 하드케이스' 확보용.

★개인정보: 수집물은 data/eval_tapo/(gitignore) 로컬 전용. 커밋·외부전송 금지.
  촬영 시 사람 있음/없음/주스병 등 오탐 유발 사물이 골고루 들어가게 연출 권장.

사용:  python tools/collect_tapo_eval.py --cam test.1 --minutes 30 --interval 5
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import camera_registry as reg  # noqa: E402

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|max_delay;500000")
import cv2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="test.1")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--out", default="data/eval_tapo")
    a = ap.parse_args()

    src = reg.source_of(a.cam)
    if not src:
        print(f"[오류] 카메라 '{a.cam}' source 없음(등록 확인)")
        return 1
    out = Path(a.out) / a.cam
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("[오류] RTSP 열기 실패")
        return 1
    print(f"수집 시작 → {out}  ({a.minutes}분, {a.interval}s 간격)  ※사람 유무·주스병 등 하드케이스 연출 권장")
    t_end = time.time() + a.minutes * 60
    n = 0
    try:
        while time.time() < t_end:
            ok, fr = cap.read()
            if not ok:
                time.sleep(0.5)
                continue
            stamp = datetime.now().strftime("%H%M%S")
            cv2.imwrite(str(out / f"f_{n:04d}_{stamp}.jpg"), fr)
            n += 1
            if n % 10 == 0:
                print(f"  {n}장 저장…")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        cap.release()
    print(f"완료 — {n}장 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
