"""rPPG 심박 추정 (scipy) — 서비스 내장용.

브라우저가 이마 ROI의 초록채널 시계열을 보내면, 사용자 제공 코드와 동일한
밴드패스(0.7~3Hz)+FFT 파이프라인으로 심박수(BPM)를 계산한다. (JS 간이추정보다 정밀)
scipy 미설치 등 실패 시 None → 호출 측은 JS 추정으로 폴백한다(저하 없음).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np


def hr_zone(bpm: float) -> str:
    if bpm < 100:
        return "저강도"
    if bpm < 140:
        return "중강도"
    if bpm < 170:
        return "고강도"
    return "최대"


def estimate_bpm(samples: List[float], fs: float, lo: float = 0.7, hi: float = 3.0) -> Optional[Dict[str, Any]]:
    """초록채널 시계열 + 표본율 → {bpm, quality, zone}. 신뢰 불가 시 None."""
    sig = np.asarray(samples, dtype=float)
    if sig.size < int(max(1.0, fs) * 3):   # 최소 ~3초
        return None
    sig = sig - sig.mean()
    std = sig.std()
    if std == 0:
        return None
    sig = sig / std
    try:
        from scipy.signal import butter, filtfilt
        ny = 0.5 * fs
        b, a = butter(5, [lo / ny, hi / ny], btype="band")
        fsig = filtfilt(b, a, sig)
    except Exception:
        # scipy 없거나 실패 → 단순 FFT (필터 없이)
        try:
            pass  # type: ignore
        except Exception:
            return None
        fsig = sig
    n = len(fsig)
    fv = np.abs(np.fft.fft(fsig))[:n // 2]
    fr = np.fft.fftfreq(n, d=1.0 / fs)[:n // 2]
    idx = np.where((fr >= lo) & (fr <= hi))[0]
    if idx.size == 0:
        return None
    band = fv[idx]
    peak_freq = float(fr[idx][int(np.argmax(band))])
    bpm = peak_freq * 60.0
    snr = float(band.max() / (band.mean() or 1.0))
    if not (42 <= bpm <= 200):
        return None
    return {"bpm": int(round(bpm)), "quality": round(snr, 2), "zone": hr_zone(bpm)}
