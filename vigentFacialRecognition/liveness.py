"""liveness.py — 라이브니스(생체 진위) 검출: 사진·화면 위조 차단

문제: 얼굴 인식만으로는 **사진/휴대폰 화면**을 들이대도 통과한다(presentation attack).
해결: '살아있는 진짜 사람'인지 확인하는 단계를 얼굴 매칭 앞에 둔다.

두 신호(둘 다 라이선스 안전, 기존 자산 재사용):
  1) 능동 챌린지 — "고개를 천천히 좌우로 돌리세요". 얼굴 5점으로 머리 회전(yaw)을 추정해
     좌·우 양극을 실제로 거쳤는지 확인. 평면 사진은 3D 회전을 못 만들어 통과 못 함.
  2) 맥박(rPPG) — 사진엔 심장박동이 없다. AgitationMonitor 재사용해 맥박 검출 여부를 본다.
     (require_pulse=True 일 때만 통과 조건에 포함; 기본은 표시만)

상태형 세션: 프레임을 순서대로 update() 한다. 핵심 판정 로직(feed_metrics)은
머리회전 수치만 받으므로 단위테스트가 쉽다(실제 얼굴 불필요).
"""
from __future__ import annotations

import numpy as np

from .engine import get_engine

YAW_SIDE = 0.12       # 한쪽으로 충분히 돌렸다고 보는 |offset|
YAW_SWING = 0.30      # 좌우 진폭(max-min) 통과 기준
DEFAULT_TIMEOUT = 15.0


class LivenessSession:
    def __init__(self, require_pulse: bool = False, timeout_sec: float = DEFAULT_TIMEOUT):
        self.require_pulse = require_pulse
        self.timeout = timeout_sec
        self.instruction = "고개를 천천히 좌우로 돌려주세요"
        self.reset()

    def reset(self) -> None:
        self._t0: float | None = None
        self._min = 1e9
        self._max = -1e9
        self.passed = False
        self.failed = False
        self._pulse: bool | None = None
        self._monitor = None

    # ── 판정 핵심(테스트 가능) ───────────────────────────────
    def feed_metrics(self, offset: float | None, ts: float) -> dict:
        if self._t0 is None:
            self._t0 = ts
        elapsed = ts - self._t0
        if offset is not None:
            self._min = min(self._min, offset)
            self._max = max(self._max, offset)
        swing = (self._max - self._min) if self._max > -1e8 else 0.0
        sides_ok = (self._min < -YAW_SIDE) and (self._max > YAW_SIDE)
        active_ok = sides_ok and swing >= YAW_SWING
        pulse_ok = (not self.require_pulse) or bool(self._pulse)

        if not self.passed and not self.failed:
            if active_ok and pulse_ok:
                self.passed = True
            elif elapsed > self.timeout:
                self.failed = True

        return {
            "instruction": self.instruction,
            "swing": round(max(0.0, swing), 3),
            "progress": round(min(1.0, max(0.0, swing) / YAW_SWING), 2),
            "active_ok": active_ok,
            "passed": self.passed,
            "failed": self.failed,
            "remaining_sec": round(max(0.0, self.timeout - elapsed), 1),
            "require_pulse": self.require_pulse,
            "pulse_detected": self._pulse,
        }

    # ── 프레임 입력 ──────────────────────────────────────────
    def update(self, frame: np.ndarray, ts: float) -> dict:
        faces = get_engine().detect(frame)
        offset = None
        face_px = 0
        if faces:
            f = max(faces, key=lambda x: x.bbox[2] * x.bbox[3])
            face_px = int(min(f.bbox[2], f.bbox[3]))
            re, le, nose = f.landmarks[0], f.landmarks[1], f.landmarks[2]
            iod = float(np.linalg.norm(re - le)) or 1.0
            mid = (re + le) / 2.0
            offset = float((nose[0] - mid[0]) / iod)     # 머리 yaw 대용(좌- / 우+)
            if self.require_pulse:
                if self._monitor is None:
                    from .agitation import AgitationMonitor
                    self._monitor = AgitationMonitor()
                o = self._monitor.update(frame, ts)
                if o.get("heart_rate_bpm") is not None:
                    self._pulse = True
        out = self.feed_metrics(offset, ts)
        out["face"] = bool(faces)
        out["face_px"] = face_px
        return out
