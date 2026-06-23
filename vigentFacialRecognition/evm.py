"""evm.py — Eulerian Video Magnification (모션 확대) 실시간 엔진

미세한 떨림·맥동을 눈에 보이게 증폭한다(MIT Wu et al. 2012의 선형 EVM).
스트리밍(웹캠)용으로 IIR 시간 대역통과 + 라플라시안 피라미드를 쓴다.

원리:
  1) 프레임을 YIQ로 변환(휘도 Y / 색차 I,Q).
  2) 라플라시안 피라미드로 공간 주파수 대역 분해.
  3) 각 대역을 두 개의 1차 IIR 저역통과 차로 시간 대역통과 → 특정 주파수 운동만 추출.
  4) 공간 파장(λ_c) 기준으로 대역별 증폭계수를 정해 노이즈 억제하며 α배 증폭.
  5) 더해서 피라미드 복원 → 미세 운동이 과장된 영상.

⚠ 시각화 도구다. '거짓말/감정 판별'이 아니라 떨림을 보이게 할 뿐. (advisory)
새 의존성 없음(OpenCV/numpy). 처리 폭을 줄여(max_width) 실시간 유지.
"""
from __future__ import annotations

import cv2
import numpy as np

# RGB <-> YIQ (NTSC) 선형 변환
_RGB2YIQ = np.array([[0.299, 0.587, 0.114],
                     [0.596, -0.274, -0.322],
                     [0.211, -0.523, 0.312]], np.float32)
_YIQ2RGB = np.linalg.inv(_RGB2YIQ).astype(np.float32)


def _bgr2yiq(bgr: np.ndarray) -> np.ndarray:
    rgb = bgr[..., ::-1].astype(np.float32) / 255.0
    return rgb @ _RGB2YIQ.T


def _yiq2bgr(yiq: np.ndarray) -> np.ndarray:
    rgb = yiq @ _YIQ2RGB.T
    bgr = np.clip(rgb[..., ::-1] * 255.0, 0, 255).astype(np.uint8)
    return bgr


def _build_laplacian(img: np.ndarray, levels: int) -> list[np.ndarray]:
    gauss = [img]
    for _ in range(levels):
        gauss.append(cv2.pyrDown(gauss[-1]))
    lap = []
    for i in range(levels):
        up = cv2.pyrUp(gauss[i + 1], dstsize=(gauss[i].shape[1], gauss[i].shape[0]))
        lap.append(gauss[i] - up)
    lap.append(gauss[-1])           # 잔차(최저주파)
    return lap


def _collapse(lap: list[np.ndarray]) -> np.ndarray:
    img = lap[-1]
    for i in range(len(lap) - 2, -1, -1):
        img = cv2.pyrUp(img, dstsize=(lap[i].shape[1], lap[i].shape[0])) + lap[i]
    return img


class MotionMagnifier:
    """프레임을 순서대로 process() 하면 모션 확대된 프레임을 돌려준다(상태 유지)."""

    def __init__(self, alpha: float = 20.0, lambda_c: float = 16.0,
                 fl: float = 0.5, fh: float = 4.0, levels: int = 4,
                 chrom_atten: float = 0.3, max_width: int = 384) -> None:
        self.alpha = float(alpha)
        self.lambda_c = float(lambda_c)
        self.fl, self.fh = float(fl), float(fh)
        self.levels = int(levels)
        self.chrom_atten = float(chrom_atten)
        self.max_width = int(max_width)
        self._lp_hi: list[np.ndarray] | None = None   # IIR 저역통과(고cutoff) 상태
        self._lp_lo: list[np.ndarray] | None = None
        self._fps = 15.0
        self._last_ts: float | None = None

    def reset(self) -> None:
        self._lp_hi = self._lp_lo = None
        self._last_ts = None

    def _update_fps(self, ts: float | None) -> None:
        if ts is None:
            return
        if self._last_ts is not None:
            dt = ts - self._last_ts
            if 0 < dt < 1.0:
                self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)   # 완만 평활
        self._last_ts = ts

    def _amp_per_level(self, h: int, w: int, n: int) -> list[float]:
        """공간 파장 기준 대역별 증폭계수(노이즈 억제). 최정밀·잔차는 0."""
        delta = self.lambda_c / 8.0 / (1.0 + self.alpha)
        base = (h * h + w * w) ** 0.5 / 3.0          # 잔차(최저주파) 대표 파장
        amps = [0.0] * (n + 1)
        for l in range(n + 1):                        # 0=최정밀 … n=잔차
            lam = base / (2 ** (n - l))               # 정밀할수록 파장↓
            if l == 0 or l == n:
                amps[l] = 0.0                         # 최정밀(노이즈)·잔차(DC) 제외
            else:
                cur = lam / delta / 8.0 - 1.0
                amps[l] = max(0.0, min(self.alpha, cur))
        return amps

    def process(self, bgr: np.ndarray, ts: float | None = None) -> np.ndarray:
        self._update_fps(ts)
        H0, W0 = bgr.shape[:2]
        scale = min(1.0, self.max_width / W0)
        small = cv2.resize(bgr, (int(W0 * scale), int(H0 * scale))) if scale < 1 else bgr
        yiq = _bgr2yiq(small)
        lap = _build_laplacian(yiq, self.levels)

        # IIR 시간 대역통과 계수
        a_hi = 1.0 - np.exp(-2 * np.pi * self.fh / max(self._fps, 1.0))
        a_lo = 1.0 - np.exp(-2 * np.pi * self.fl / max(self._fps, 1.0))

        if self._lp_hi is None or len(self._lp_hi) != len(lap) \
                or self._lp_hi[0].shape != lap[0].shape:
            self._lp_hi = [b.copy() for b in lap]      # 첫 프레임: 대역통과 0에서 시작
            self._lp_lo = [b.copy() for b in lap]

        amps = self._amp_per_level(lap[0].shape[0], lap[0].shape[1], self.levels)
        out = []
        for i, band in enumerate(lap):
            self._lp_hi[i] += a_hi * (band - self._lp_hi[i])
            self._lp_lo[i] += a_lo * (band - self._lp_lo[i])
            bp = self._lp_hi[i] - self._lp_lo[i]       # 대역통과(운동 성분)
            amp = amps[i]
            if amp > 0:
                mag = bp * amp
                if mag.ndim == 3 and mag.shape[2] == 3:
                    mag[..., 1] *= self.chrom_atten    # 색차 약화(색 노이즈 억제)
                    mag[..., 2] *= self.chrom_atten
                out.append(band + mag)
            else:
                out.append(band)

        rec = _collapse(out)
        mag_bgr = _yiq2bgr(rec)
        return cv2.resize(mag_bgr, (W0, H0)) if scale < 1 else mag_bgr

    @property
    def fps(self) -> float:
        return round(self._fps, 1)
