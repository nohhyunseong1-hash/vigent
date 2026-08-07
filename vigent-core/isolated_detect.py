"""isolated_detect.py — 서로 무관한 정지 이미지 1장씩 검출할 때 쓰는 공용 헬퍼(2026-08 신설).

배경(버그, 재발 방지): `agents/guard.py`의 `_track_iou`(STALE_MAX_MISSES=1·TRACK_TTL=1.2s)는 "같은
카메라의 연속 프레임"을 전제로 잠깐의 미탐지도 이전 박스를 이어붙여 깜빡임을 없애는 설계다. 이걸 서로
무관한 정지 이미지(다른 비디오·다른 시점 사진)에 같은 track_key로 반복 호출하면, 이전 이미지의 박스가
전혀 다른 이미지의 검출 결과에 "이어붙어" 나타난다(2026-08, `benchmarks/extract_eval_frames.py`에서
실측 확인 — 세 프레임의 conf가 직전 프레임과 소수점까지 완전히 일치해 트랙 잔존임을 증명).

이 헬퍼는 매 호출마다 **고유한 track_key를 내부에서 발급**하고 사용 전/후 `reset_tracks()`로 비워
호출자가 track_key를 직접 관리하다 실수로 재사용할 여지를 원천 차단한다. `agents/guard.py`는 무수정
(정상 동작 확인됨 — 문제는 호출 패턴이지 추적 로직 자체가 아니다).

사용:
  from isolated_detect import detect_isolated
  out = detect_isolated(guard, img, detectors=["person"], conf=0.10, imgsz=640)
"""
from __future__ import annotations

import uuid
from typing import Any


def detect_isolated(guard: Any, img: Any, detectors: list[str],
                     conf: float | None = None, imgsz: int | None = None) -> dict[str, Any]:
    """서로 무관한 정지 이미지 1장을 격리된 트랙 상태로 검출한다(연속 영상엔 쓰지 말 것 — 그 경우는
    같은 track_key를 프레임 내내 재사용하는 게 정답이다, `benchmarks/box_quality.py`의
    `replay_detections`가 그 예시). track_key는 매번 새로 발급하므로 호출자가 신경 쓸 필요 없다."""
    track_key = f"isolated:{uuid.uuid4().hex[:12]}"
    guard.reset_tracks(track_key)   # 방어적(신규 키라 원래 비어있음) — 신규 key 발급 방침이 깨져도 안전
    out = guard.detect(img, detectors=detectors, conf=conf, imgsz=imgsz, track_key=track_key)
    guard.reset_tracks(track_key)   # 사용 후 정리 — 대량 배치에서 _tracks_by_key 무한 증식 방지
    return out
