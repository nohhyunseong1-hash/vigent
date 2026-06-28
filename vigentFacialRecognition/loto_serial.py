"""loto_serial.py — Arduino 잠금장치 시리얼 컨트롤러 (장비/라이브러리 없으면 시뮬레이션)

PC → Arduino 로 LOCK/UNLOCK 명령을 보낸다. pyserial 미설치 또는 포트 미연결이면
**시뮬레이션 모드로 폴백**(절대 저하 없음) — 상태는 메모리로 추적해 데모/테스트 가능.

포트: 환경변수 VIGENT_LOTO_PORT (예: /dev/tty.usbmodemXXXX, COM3). 없으면 시뮬레이션.
페일세이프: 초기 상태 = 잠금(locked=True).
"""
from __future__ import annotations

import os
import time


class LotoController:
    def __init__(self, port: str | None = None, baud: int = 9600):
        self.port = port or os.environ.get("VIGENT_LOTO_PORT") or self._autodetect()
        self.baud = baud
        self.locked = True                 # 페일세이프 기본
        self._serial = None
        self.simulated = True
        self._connect()

    @staticmethod
    def _autodetect() -> str | None:
        """USB 시리얼 보드 포트를 자동 탐색(아두이노 클론 포함)."""
        import glob
        for pat in ("/dev/cu.usbserial*", "/dev/cu.usbmodem*",
                    "/dev/cu.wchusbserial*", "/dev/cu.SLAB_USBtoUART*"):
            hits = glob.glob(pat)
            if hits:
                return hits[0]
        return None

    def _connect(self) -> None:
        if not self.port:
            return                         # 시뮬레이션 유지
        try:
            import serial                   # pyserial
            self._serial = serial.Serial(self.port, self.baud, timeout=1)
            time.sleep(2.0)                 # 아두이노 리셋 대기
            self.simulated = False
            self._send("LOCK")              # 연결 직후 안전상태 강제
        except Exception:
            self._serial = None
            self.simulated = True           # 실패 → 시뮬레이션 폴백

    def _send(self, cmd: str) -> str:
        if self._serial is not None:
            try:
                self._serial.write((cmd + "\n").encode())
                return self._serial.readline().decode(errors="ignore").strip()
            except Exception:
                self.simulated = True       # 통신 실패 → 폴백
        return f"SIM:{cmd}"

    # ── 제어 ─────────────────────────────────────────────────
    def set_locked(self, locked: bool) -> None:
        """locked=True → 기계 비활성(서보 LOCKED). False → 기동 허용."""
        self.locked = locked
        self._send("LOCK" if locked else "UNLOCK")

    def ping(self) -> bool:
        return self._send("PING") in ("PONG", "SIM:PING")

    def status(self) -> dict:
        return {"locked": self.locked, "simulated": self.simulated,
                "port": self.port or "(none)"}
