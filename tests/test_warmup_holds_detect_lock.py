"""[CODE_REVIEW M1-4] 예열(readiness.warmup)이 guard.detect 를 DETECT_LOCK 안에서 부르는지.

배경: 예열 스레드는 서버가 이미 응답 중일 때 돈다. 예열이 락 없이 guard.detect() 를 부르면
`/detect/frame`(락 보유)이 같은 슬롯의 지연 로드(`_get_model`)에 동시에 들어갈 수 있다 —
같은 모델 이중 로드(VRAM 2배) 또는 부분 초기화 import 경합(detectors/rfdetr_adapter.py 상단 기록).
호출부 4곳(worker·/detect/frame·/safety/voice/scene·warmup) 중 warmup 만 무락이었다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import readiness  # noqa: E402
from app_state import DETECT_LOCK  # noqa: E402


class _LockCheckingGuard:
    def __init__(self):
        self.owned_at_call: list[bool] = []

    def detect(self, img, detectors=None, track_key=None):
        self.owned_at_call.append(bool(DETECT_LOCK._is_owned()))
        return {"detections": []}


class WarmupHoldsDetectLock(unittest.TestCase):
    def setUp(self):
        # 다른 모듈이 남긴 실모델 예열 스레드가 락·상태를 잡고 있을 수 있다(R12) — 먼저 기다린다
        import threading
        for t in threading.enumerate():
            if t.name == "vigent-warmup" and t is not threading.current_thread():
                t.join(90.0)
        readiness._mark(readiness.STARTING)

    def test_every_warmup_detect_call_holds_lock(self):
        g = _LockCheckingGuard()
        with mock.patch.object(readiness, "required_weights_missing", return_value=[]):
            r = readiness.warmup(g, ["person", "ppe"])
        self.assertTrue(r["ok"])
        self.assertEqual(g.owned_at_call, [True, True],
                         f"예열 detect 호출이 DETECT_LOCK 없이 실행됨: {g.owned_at_call}")

    def test_lock_released_after_warmup(self):
        """예열이 끝나면 락을 놓아야 한다 — 워커·라우터가 영원히 기다리면 안 된다."""
        with mock.patch.object(readiness, "required_weights_missing", return_value=[]):
            readiness.warmup(_LockCheckingGuard(), ["person"])
        self.assertFalse(DETECT_LOCK._is_owned())
        self.assertTrue(DETECT_LOCK.acquire(blocking=False), "예열 후 락이 풀리지 않았다")
        DETECT_LOCK.release()


if __name__ == "__main__":
    unittest.main()
