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


def _match_embedding(emb: np.ndarray, gallery, owners, th: float):
    """임베딩 1개를 갤러리와 비교 → (person_id, name, similarity)."""
    if gallery.shape[0] == 0:
        return None, None, 0.0
    sims = gallery @ emb
    j = int(np.argmax(sims))
    sim = float(sims[j])
    if sim >= th:
        pid = owners[j]
        return pid, get_store().name_of(pid), sim
    return None, None, sim


def identify_fused(frames: list[np.ndarray], *, threshold: float | None = None,
                   audit: bool = True) -> Match | None:
    """멀티프레임 융합 식별(키오스크/게이트 1인 시나리오).

    여러 프레임에서 가장 크고 품질 좋은 얼굴 임베딩을 모아 평균(fuse)한 뒤 한 번만
    매칭한다. 단일 프레임보다 흔들림·표정·조명 노이즈에 강해 정확도가 오른다.
    얼굴을 한 번도 못 잡으면 None.
    """
    privacy.require_enabled()
    th = config.COSINE_THRESHOLD if threshold is None else threshold
    eng = get_engine()
    gallery, owners = get_store().gallery_matrix()

    probes: list[np.ndarray] = []
    bbox = (0, 0, 0, 0)
    score = 0.0
    for fr in frames:
        dets = eng.detect_and_embed(fr, quality_filter=True)
        if not dets:
            continue
        face, emb = max(dets, key=lambda d: d[0].bbox[2] * d[0].bbox[3])
        probes.append(emb)
        bbox, score = face.bbox, face.score

    if not probes:
        return None
    fused = eng.fuse(probes)
    pid, name, sim = _match_embedding(fused, gallery, owners, th)
    if audit:
        privacy.audit("identify_fused", frames=len(frames), used=len(probes),
                      matched=pid, similarity=round(sim, 4))
    return Match(bbox=bbox, person_id=pid, name=name,
                 similarity=round(sim, 4), detect_score=round(score, 4))


class TemporalVoter:
    """K-연속 일치 확정기(스트리밍용).

    매 프레임의 식별 결과(person_id 또는 None)를 넣으면, 같은 사람이 연속 K번
    나와야 비로소 '확정'을 돌려준다. 한 프레임짜리 오인식이 게이트를 여는 걸 막는다.

        voter = TemporalVoter(k=3)
        confirmed = voter.update(match.person_id)   # K번 연속 전에는 None
    """

    def __init__(self, k: int | None = None) -> None:
        self.k = k or config.VOTE_K
        self._last: str | None = None
        self._count = 0
        self._confirmed: str | None = None

    def update(self, person_id: str | None) -> str | None:
        if person_id is not None and person_id == self._last:
            self._count += 1
        else:
            self._last = person_id
            self._count = 1 if person_id is not None else 0
        if self._count >= self.k:
            self._confirmed = self._last
            return self._confirmed
        return None

    def reset(self) -> None:
        self._last, self._count, self._confirmed = None, 0, None
