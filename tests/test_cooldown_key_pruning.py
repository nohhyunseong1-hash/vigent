"""[CODE_REVIEW M3-4] 규칙 쿨다운 키(`rule|t<tid>`)는 만료 후 정리돼야 한다(M2-1 동류).

배경: worker._process_frame 의 ctx.cooldown 은 발화 주체마다 키를 만들고(zone_intrusion 은 사람 단위)
지우지 않았다 → 운영 일수만큼 누적. 계약: ① 쿨다운 안의 키는 유지(억제 동작 불변)
② 만료(_COOLDOWN_S 경과)된 키는 제거 ③ 300명 순차 진입 시뮬에서 키 수가 상한(창 크기) 안에 머문다.
"""
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import worker as W  # noqa: E402
from _isolate import isolate_alerts, isolate_data_dirs  # noqa: E402


class _NoGuard:
    def detect(self, frame, detectors=None, track_key="default"):
        return {"detections": [], "signals": {}, "person_count": 0}


def _ctx():
    mtrack = type("M", (), {"update": lambda s, d, t: []})()
    etrack = type("E", (), {"update": lambda s, f, t, b: []})()
    return W._FrameCtx(["person"], [], mtrack, etrack, False, 30.0, ROOT / "data" / "x", "TESTCAM", "test://src")


class CooldownKeyPruning(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.addCleanup(isolate_data_dirs())
        self.w = W.Worker()
        self.ctx = _ctx()
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.lock = threading.Lock()

    def _frame(self, t: float, subject: str):
        fired = [("zone_intrusion", "high", "n", subject)]
        with mock.patch.object(W, "_derive", return_value=fired), \
                mock.patch.object(W.time, "time", return_value=t), \
                mock.patch.object(W.data_engine, "log_event", return_value={}):
            self.w._process_frame(self.frame, t, _NoGuard(), self.lock, self.ctx)

    def test_active_key_kept_and_suppresses(self):
        self._frame(100.0, "t1")
        self._frame(105.0, "t1")                       # 쿨다운(15s) 안 — 억제
        self.assertIn("zone_intrusion|t1", self.ctx.cooldown)
        self.assertEqual(self.w.state["events"], 1)

    def test_expired_key_removed(self):
        self._frame(100.0, "t1")
        self._frame(100.0 + W._COOLDOWN_S + 1.0, "t2")   # t1 은 만료
        self.assertNotIn("zone_intrusion|t1", self.ctx.cooldown)
        self.assertIn("zone_intrusion|t2", self.ctx.cooldown)

    def test_long_run_is_bounded(self):
        for i in range(300):                            # 0.5s 마다 새 사람
            self._frame(100.0 + i * 0.5, f"t{i}")
        bound = int(W._COOLDOWN_S / 0.5) + 2             # 창 안에 있을 수 있는 키 수
        self.assertLessEqual(len(self.ctx.cooldown), bound, f"쿨다운 키가 누적된다: {len(self.ctx.cooldown)}")
        self.assertEqual(self.w.state["events"], 300)   # 기록 자체는 사람마다 1건(억제 없음)


if __name__ == "__main__":
    unittest.main()
