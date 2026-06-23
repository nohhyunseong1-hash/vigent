"""engine.py — 얼굴 검출 + 임베딩 추출 엔진 (YuNet + SFace)

기술 핵심:
  - 검출: OpenCV FaceDetectorYN(YuNet, MIT). 얼굴 박스 + 5점 랜드마크.
  - 인식: OpenCV FaceRecognizerSF(SFace, Apache-2.0). 랜드마크로 정렬 후 128차원 임베딩.
  - 임베딩은 L2 정규화 → 갤러리와 '코사인 유사도 = 내적'으로 빠르게 비교(벡터화).

성능: CPU에서 얼굴당 검출+임베딩 보통 10~50ms → 1초 요건 충분.
정확도: SFace LFW 99.4% → 임계값 조정으로 95%+ 운용.

폴백(절대 저하 없음):
  - 모델 파일이 없거나 로드 실패 시 RuntimeError 를 던지되, 상위(recognizer/api)에서
    잡아 '얼굴 인식 비활성'으로 처리하고 나머지 VIGENT 기능은 그대로 둔다.
"""
from __future__ import annotations

import threading
from typing import NamedTuple

import cv2
import numpy as np

from . import config


class Face(NamedTuple):
    """검출된 얼굴 한 개."""
    bbox: tuple[int, int, int, int]      # x, y, w, h
    score: float                          # 검출 신뢰도
    landmarks: np.ndarray                 # 5점(눈·코·입) (5,2)
    row: np.ndarray                       # YuNet 원시 행(정렬 alignCrop 입력용)


class FaceEngine:
    """검출기·인식기를 1회 로드해 캐시하는 엔진. 추론은 락으로 직렬화(스레드 안전)."""

    def __init__(self) -> None:
        if not config.model_files_present():
            raise RuntimeError(
                "얼굴 인식 모델 파일이 없습니다. "
                "`python -m vigentFacialRecognition.download_models` 로 먼저 받으세요."
            )
        # 입력 크기는 detect() 때 프레임마다 setInputSize 로 갱신한다.
        self._det = cv2.FaceDetectorYN.create(
            str(config.YUNET_PATH), "", (320, 320),
            config.DETECT_SCORE_THRESHOLD, config.DETECT_NMS_THRESHOLD, config.DETECT_TOP_K,
        )
        self._rec = cv2.FaceRecognizerSF.create(str(config.SFACE_PATH), "")
        self._lock = threading.Lock()

    # ── 검출 ──────────────────────────────────────────────────
    def detect(self, img: np.ndarray) -> list[Face]:
        """BGR 이미지에서 얼굴들을 검출. 없으면 빈 리스트."""
        h, w = img.shape[:2]
        with self._lock:
            self._det.setInputSize((w, h))
            _, faces = self._det.detect(img)
        if faces is None:
            return []
        out: list[Face] = []
        for row in faces:
            x, y, fw, fh = row[:4].astype(int)
            lmk = row[4:14].reshape(5, 2)
            out.append(Face(
                bbox=(int(x), int(y), int(fw), int(fh)),
                score=float(row[14]),
                landmarks=lmk,
                row=row,
            ))
        return out

    # ── 임베딩 ────────────────────────────────────────────────
    def embed(self, img: np.ndarray, face: Face) -> np.ndarray:
        """검출된 얼굴 한 개 → L2 정규화된 128차원 임베딩(float32)."""
        with self._lock:
            aligned = self._rec.alignCrop(img, face.row)
            feat = self._rec.feature(aligned)           # (1,128)
        v = np.asarray(feat, dtype=np.float32).reshape(-1)
        n = np.linalg.norm(v)
        return v / n if n > 0 else v

    # ── 품질 게이트 ───────────────────────────────────────────
    @staticmethod
    def quality_ok(face: Face) -> bool:
        """정확도 보호: 너무 작거나 과도하게 기울어진(역상 포함) 얼굴은 배제.

        - 크기: 얼굴 짧은 변 ≥ MIN_FACE_PX.
        - 정면성: 좌·우 눈 랜드마크를 잇는 선의 기울기 ≤ MAX_EYE_TILT_DEG.
        """
        w, h = face.bbox[2], face.bbox[3]
        if min(w, h) < config.MIN_FACE_PX:
            return False
        (rx, ry), (lx, ly) = face.landmarks[0], face.landmarks[1]   # 오른눈, 왼눈
        tilt = abs(np.degrees(np.arctan2(ly - ry, lx - rx)))
        tilt = min(tilt, abs(180 - tilt))     # 역상(≈180°)도 큰 기울기로 본다
        return tilt <= config.MAX_EYE_TILT_DEG

    def detect_and_embed(self, img: np.ndarray, *, quality_filter: bool = False
                         ) -> list[tuple[Face, np.ndarray]]:
        """검출 + 각 얼굴 임베딩을 한 번에. quality_filter=True면 저품질 얼굴 제외."""
        faces = self.detect(img)
        if quality_filter:
            faces = [f for f in faces if self.quality_ok(f)]
        return [(f, self.embed(img, f)) for f in faces]

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        """두 (정규화된) 임베딩의 코사인 유사도."""
        return float(np.dot(a, b))


# 모듈 전역 싱글턴(지연 로딩) — 무거운 모델을 매번 만들지 않는다.
_ENGINE: FaceEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> FaceEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = FaceEngine()
    return _ENGINE
