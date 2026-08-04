"""worker.Worker._process_frame 단위 테스트 (P2-13 추출 대상).

_loop 에서 분리한 프레임 처리부(수집·추론·트래커·발화·쿨다운·이벤트로깅)를
스텁 guard/트래커 + log_event 목킹으로 격리 검증한다.
※ 이 테스트는 _process_frame 단독만 본다. _loop 와의 통합(ctx 전달·예외 전파)은
  별도 런타임 스모크로 확인한다(리팩터 회귀 방지).
"""
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import data_engine  # noqa: E402
import worker  # noqa: E402


def _ctx(detectors=None, zone=None, collect_on=False):
    # 트래커는 발화 없음으로 고정(포즈모델 로드 회피·결정론).
    ftrack = type("F", (), {"update": lambda self, f, t, b: (False, "")})()
    mtrack = type("M", (), {"update": lambda self, d, t: []})()
    etrack = type("E", (), {"update": lambda self, f, t, b: []})()
    return worker._FrameCtx(detectors or ["person"], zone or [], ftrack, mtrack, etrack,
                            collect_on, 30.0, ROOT / "data" / "dataset" / "images", "TESTCAM", "test://src")


class _FireGuard:
    """fire_smoke 신호를 항상 내는 스텁 — _derive 가 결정론적으로 발화."""
    def detect(self, frame, detectors=None, track_key="default"):
        return {"signals": {"fire_smoke": True}, "detections": [], "person_count": 0}


class _RaisingGuard:
    def detect(self, frame, detectors=None, track_key="default"):
        raise RuntimeError("boom")


class TestProcessFrame(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.lock = threading.Lock()
        self.worker = worker.Worker()
        self._orig_log = data_engine.log_event
        self.logged = []
        data_engine.log_event = lambda **kw: self.logged.append(kw)

    def tearDown(self):
        data_engine.log_event = self._orig_log

    def test_fire_smoke_fires_and_logs(self):
        ctx = _ctx()
        self.worker._process_frame(self.frame, 100.0, _FireGuard(), self.lock, ctx)
        self.assertEqual(len(self.logged), 1)
        self.assertEqual(self.logged[0]["rule"], "fire_smoke")
        self.assertEqual(self.logged[0]["level"], "critical")
        self.assertEqual(self.worker.state["events"], 1)
        self.assertEqual(self.worker.state["last_event"], "fire_smoke(critical)")
        self.assertIn("fire_smoke", ctx.cooldown)

    def test_cooldown_suppresses_repeat(self):
        ctx = _ctx()
        self.worker._process_frame(self.frame, 100.0, _FireGuard(), self.lock, ctx)
        # 같은 규칙을 쿨다운 이내(직후)에 다시 → 재로깅 없음
        self.worker._process_frame(self.frame, 100.1, _FireGuard(), self.lock, ctx)
        self.assertEqual(len(self.logged), 1)
        self.assertEqual(self.worker.state["events"], 1)

    def test_no_signal_no_event(self):
        ctx = _ctx()
        guard = type("G", (), {"detect": lambda self, f, detectors=None:
                               {"signals": {}, "detections": [], "person_count": 0}})()
        self.worker._process_frame(self.frame, 100.0, guard, self.lock, ctx)
        self.assertEqual(len(self.logged), 0)
        self.assertEqual(self.worker.state["events"], 0)

    def test_exception_isolated_not_propagated(self):
        ctx = _ctx()
        # guard 가 예외를 던져도 _process_frame 은 삼키고 state["error"] 기록(루프 유지 계약)
        self.worker._process_frame(self.frame, 100.0, _RaisingGuard(), self.lock, ctx)
        self.assertIn("boom", self.worker.state["error"])
        self.assertEqual(self.worker.state["events"], 0)


if __name__ == "__main__":
    unittest.main()
