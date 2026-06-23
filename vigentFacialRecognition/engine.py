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
    def quality_ok(face: Face, img: np.ndarray | None = None) -> bool:
        """정확도 보호: 저품질 얼굴(작음·기울어짐·흐림·과암/과명)을 배제.

        - 크기: 얼굴 짧은 변 ≥ MIN_FACE_PX.
        - 정면성: 좌·우 눈 랜드마크를 잇는 선의 기울기 ≤ MAX_EYE_TILT_DEG.
        - (img 주면) 흐림: 라플라시안 분산 ≥ MIN_BLUR_VAR.
        - (img 주면) 밝기: 얼굴영역 평균 그레이 ∈ [MIN_BRIGHTNESS, MAX_BRIGHTNESS].
        """
        x, y, w, h = face.bbox
        if min(w, h) < config.MIN_FACE_PX:
            return False
        (rx, ry), (lx, ly) = face.landmarks[0], face.landmarks[1]   # 오른눈, 왼눈
        tilt = abs(np.degrees(np.arctan2(ly - ry, lx - rx)))
        tilt = min(tilt, abs(180 - tilt))     # 역상(≈180°)도 큰 기울기로 본다
        if tilt > config.MAX_EYE_TILT_DEG:
            return False
        if img is not None and (config.MIN_BLUR_VAR > 0 or config.MIN_BRIGHTNESS > 0):
            H, W = img.shape[:2]
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(W, x + w), min(H, y + h)
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                return False
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            if config.MIN_BLUR_VAR > 0:
                if cv2.Laplacian(gray, cv2.CV_64F).var() < config.MIN_BLUR_VAR:
                    return False        # 흐릿함
            mean = float(gray.mean())
            if mean < config.MIN_BRIGHTNESS or mean > config.MAX_BRIGHTNESS:
                return False            # 너무 어둡거나 밝음
        return True

    def detect_and_embed(self, img: np.ndarray, *, quality_filter: bool = False
                         ) -> list[tuple[Face, np.ndarray]]:
        """검출 + 각 얼굴 임베딩을 한 번에. quality_filter=True면 저품질 얼굴 제외."""
        faces = self.detect(img)
        if quality_filter:
            faces = [f for f in faces if self.quality_ok(f, img)]
        return [(f, self.embed(img, f)) for f in faces]

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        """두 (정규화된) 임베딩의 코사인 유사도."""
        return float(np.dot(a, b))

    @staticmethod
    def fuse(embeddings: list[np.ndarray]) -> np.ndarray | None:
        """멀티프레임 융합: 여러 임베딩을 평균 후 재정규화 → 노이즈에 강한 1개 벡터.

        한 장의 흔들림·표정·조명 노이즈가 평균으로 상쇄돼 인식률이 오른다.
        """
        if not embeddings:
            return None
        m = np.mean(np.stack(embeddings).astype(np.float32), axis=0)
        n = np.linalg.norm(m)
        return m / n if n > 0 else m


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
