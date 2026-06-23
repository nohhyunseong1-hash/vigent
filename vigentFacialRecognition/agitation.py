"""agitation.py — 안전용 '동요/피로' advisory 지표 (얼굴 미세떨림 + rPPG 심박)

목적(중요): 이 모듈은 **안전 보조 신호**다. 작업자의 과도한 동요·피로 가능성을
'참고용'으로 알려 휴식·점검을 유도하는 것이 전부다.
  - ❌ 거짓말 탐지/감정 판별/위협 인물 지목 용도로 쓰지 않는다(과학적 미검증·법적 위험).
  - ✅ 항상 advisory: 수치를 사람이 해석, 자동 불이익 결정 금지, 면책 문구 동반.

측정 원리(영상만으로, 새 의존성 없음):
  1) 동요 지수: 얼굴 5점 랜드마크를 프레임마다 추적 → 눈 사이 거리로 정규화(스케일 불변)
     → 단기 추세 제거 후 잔차 RMS = 미세 흔들림 양. 본인 세션 기준선 대비 상대값(z)으로 등급.
     ※ 일반 웹캠 fps로는 8~12Hz 생리적 떨림 전체를 못 잡는다 → '미세 동요'의 근사 지표임.
  2) 심박(rPPG): 이마 ROI의 RGB 시계열에 POS 알고리즘(Wang 2017) → 대역통과 FFT 피크.
     신호 품질(SNR)이 낮으면 None 으로 폴백(동요 지수만 보고).

절대 저하 없음: 얼굴이 없거나 신호가 불안정하면 해당 항목만 비고, 나머지는 동작.
"""
from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from .engine import get_engine

DISCLAIMER = ("참고용 동요/피로 지표입니다. 감정·거짓말·위협 판별이 아니며, "
              "의료 진단이 아닙니다. 불이익 결정의 근거로 쓰지 말고 사람이 확인하세요.")


class AgitationMonitor:
    """프레임을 순서대로 넣으면(update) 동요 지수·심박을 갱신해 돌려주는 상태 객체.

    한 사람(세션) 기준. 새 사람이면 reset().
    """

    def __init__(self, window_sec: float = 12.0, max_fps: float = 30.0) -> None:
        cap = int(window_sec * max_fps)
        self.ts: deque[float] = deque(maxlen=cap)
        self.lmk: deque[np.ndarray] = deque(maxlen=cap)      # 정규화 랜드마크(10,)
        self.rgb: deque[np.ndarray] = deque(maxlen=cap)      # 이마 ROI 평균 RGB(3,)
        self.tremor_hist: deque[float] = deque(maxlen=600)   # 기준선 추정용
        self._t = 0.0

    def reset(self) -> None:
        self.ts.clear(); self.lmk.clear(); self.rgb.clear(); self.tremor_hist.clear()
        self._t = 0.0

    # ── 메인 ──────────────────────────────────────────────────
    def update(self, frame: np.ndarray, ts: float | None = None) -> dict:
        # 타임스탬프(초). 안 주면 균일 증가 가정(0.05s).
        if ts is None:
            self._t += 0.05; ts = self._t

        faces = get_engine().detect(frame)
        if not faces:
            return self._out(face=False)
        f = max(faces, key=lambda x: x.bbox[2] * x.bbox[3])

        # 1) 동요용 정규화 랜드마크
        lmk = f.landmarks.astype(np.float32)              # (5,2)
        iod = float(np.linalg.norm(lmk[0] - lmk[1])) or 1.0   # 두 눈 사이
        norm = ((lmk - lmk.mean(0)) / iod).reshape(-1)    # 위치·스케일 불변
        # 2) rPPG용 이마 ROI 평균 RGB
        rgb = self._forehead_rgb(frame, f.bbox)

        self.ts.append(ts); self.lmk.append(norm); self.rgb.append(rgb)

        tremor = self._tremor()
        if tremor is not None:
            self.tremor_hist.append(tremor)
        hr, hr_q = self._heart_rate()
        return self._out(face=True, tremor=tremor, hr=hr, hr_quality=hr_q,
                         face_px=int(min(f.bbox[2], f.bbox[3])))

    # ── 동요 지수 ─────────────────────────────────────────────
    def _tremor(self) -> float | None:
        if len(self.lmk) < 12:
            return None
        A = np.stack(self.lmk)                # (T,10)
        # 단기 이동평균 제거(추세 제거) → 잔차 = 미세 흔들림
        k = max(3, min(9, len(A) // 4))
        if k % 2 == 0:
            k += 1                            # 홀수 창(중심 정렬)
        pad = k // 2
        kernel = np.ones(k) / k
        cols = []
        for c in range(A.shape[1]):
            ma = np.convolve(A[:, c], kernel, mode="same")
            cols.append((A[:, c] - ma)[pad:-pad])    # 가장자리 인공물 제거
        resid = np.stack(cols, axis=1)        # (T-2pad, 10)
        if resid.shape[0] < 4:
            return None
        recent = resid[-max(8, resid.shape[0] // 2):]
        return float(np.sqrt((recent ** 2).mean()) * 1000.0)   # 보기 좋은 스케일

    def _level(self, tremor: float | None) -> tuple[str, float]:
        """본인 세션 기준선 대비 상대 등급(z). 데이터 부족하면 '측정중'."""
        if tremor is None or len(self.tremor_hist) < 40:
            return "측정중", 0.0
        h = np.array(self.tremor_hist)
        med = float(np.median(h))
        mad = float(np.median(np.abs(h - med))) * 1.4826 + 1e-6
        z = (tremor - med) / mad
        if z >= 3.5:
            return "휴식 권고(참고)", z
        if z >= 2.0:
            return "주의(참고)", z
        return "안정", z

    # ── rPPG 심박 ─────────────────────────────────────────────
    def _forehead_rgb(self, frame: np.ndarray, bbox) -> np.ndarray:
        x, y, w, h = bbox
        H, W = frame.shape[:2]
        x0 = max(0, int(x + 0.30 * w)); x1 = min(W, int(x + 0.70 * w))
        y0 = max(0, int(y + 0.05 * h)); y1 = min(H, int(y + 0.22 * h))
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            return np.array([0, 0, 0], np.float32)
        b, g, r = roi.reshape(-1, 3).mean(0)          # OpenCV=BGR
        return np.array([r, g, b], np.float32)

    def _heart_rate(self) -> tuple[float | None, float]:
        if len(self.ts) < 64:
            return None, 0.0
        t = np.array(self.ts); dur = t[-1] - t[0]
        if dur < 6.0:                                  # 6초 미만이면 불안정
            return None, 0.0
        fs = (len(t) - 1) / dur
        # 비균일 타임스탬프 → 균일 격자 보간
        N = int(dur * fs); N = max(64, min(N, 1024))
        grid = np.linspace(t[0], t[-1], N)
        C = np.stack(self.rgb)                          # (T,3) R,G,B
        Cu = np.stack([np.interp(grid, t, C[:, i]) for i in range(3)])  # (3,N)
        # POS (Wang 2017)
        mean = Cu.mean(1, keepdims=True)
        Cn = Cu / (mean + 1e-8)
        S = np.array([[0, 1, -1], [-2, 1, 1]], np.float32) @ Cn         # (2,N)
        alpha = (S[0].std() / (S[1].std() + 1e-8))
        pulse = S[0] + alpha * S[1]
        pulse = pulse - pulse.mean()
        pulse *= np.hamming(N)
        # 스펙트럼 → 0.7~4Hz(42~240bpm) 대역 피크
        spec = np.abs(np.fft.rfft(pulse))
        freq = np.fft.rfftfreq(N, 1.0 / fs)
        band = (freq >= 0.7) & (freq <= 4.0)
        if not band.any():
            return None, 0.0
        bp = spec[band]; bf = freq[band]
        j = int(np.argmax(bp))
        snr = float(bp[j] / (bp.mean() + 1e-8))        # 피크 돌출도 = 신뢰도
        if snr < 3.0:                                   # 신호 약하면 폴백
            return None, round(snr, 2)
        return round(float(bf[j] * 60.0), 1), round(snr, 2)

    # ── 출력 ──────────────────────────────────────────────────
    def _out(self, *, face: bool, tremor=None, hr=None, hr_quality=0.0,
             face_px: int = 0) -> dict:
        level, z = self._level(tremor)
        return {
            "face": face,
            "tremor": None if tremor is None else round(tremor, 2),
            "tremor_z": round(z, 2),
            "level": level if face else "얼굴없음",
            "heart_rate_bpm": hr,
            "hr_quality": hr_quality,
            "face_px": face_px,
            "samples": len(self.ts),
            "advisory": True,
            "disclaimer": DISCLAIMER,
        }
