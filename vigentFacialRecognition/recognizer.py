"""recognizer.py — 고수준 식별 API (검출 → 임베딩 → 갤러리 매칭)

identify(frame): 프레임에서 얼굴들을 찾아, 등록된 사람과 코사인 유사도로 매칭한다.
  - 유사도 ≥ 임계값 → 그 사람으로 식별, 미만 → 'unknown'.
  - 갤러리 전체와 벡터화 내적(코사인)으로 한 번에 비교 → 빠름.

절대 저하 없음: 엔진/모델이 없으면 빈 결과 + 사유를 돌려주고 예외로 죽지 않는다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from . import config, privacy
from .engine import get_engine
from .enrollment import get_store


@dataclass
class Match:
    bbox: tuple[int, int, int, int]
    person_id: str | None        # None = unknown
    name: str | None
    similarity: float            # 최고 코사인 유사도
    detect_score: float


def identify(frame: np.ndarray, *, threshold: float | None = None,
             audit: bool = True) -> list[Match]:
    """프레임(BGR)에서 얼굴 식별. 옵트인 OFF면 FacialRecognitionDisabled."""
    privacy.require_enabled()
    th = config.COSINE_THRESHOLD if threshold is None else threshold
    eng = get_engine()
    store = get_store()
    gallery, owners = store.gallery_matrix()

    results: list[Match] = []
    for face, emb in eng.detect_and_embed(frame, quality_filter=True):
        person_id: str | None = None
        name: str | None = None
        sim = 0.0
        if gallery.shape[0] > 0:
            sims = gallery @ emb              # (M,) 코사인(정규화 가정)
            j = int(np.argmax(sims))
            sim = float(sims[j])
            if sim >= th:
                person_id = owners[j]
                name = store.name_of(person_id)
        results.append(Match(
            bbox=face.bbox, person_id=person_id, name=name,
            similarity=round(sim, 4), detect_score=round(face.score, 4),
        ))

    if audit:
        ids = [m.person_id for m in results if m.person_id]
        privacy.audit("identify", faces=len(results),
                      matched=ids, unknown=len(results) - len(ids))
    return results


def identify_timed(frame: np.ndarray, **kw) -> tuple[list[Match], float]:
    """식별 + 소요시간(ms). 1초 요건 모니터링/벤치마크용."""
    t0 = time.perf_counter()
    out = identify(frame, **kw)
    return out, (time.perf_counter() - t0) * 1000.0
