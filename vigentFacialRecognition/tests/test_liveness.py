"""test_liveness.py — 라이브니스 판정 로직 검증 (실제 얼굴 불필요)

실행: cd ~/Desktop/VIGENT && python -m unittest vigentFacialRecognition.tests.test_liveness
"""
import unittest

from vigentFacialRecognition.liveness import LivenessSession


class TestLiveness(unittest.TestCase):
    def test_real_head_turn_passes(self):
        s = LivenessSession()
        # 고개를 좌우로 돌리는 시퀀스(offset 가 -0.2 ~ +0.2 로 스윙)
        seq = [0, -0.1, -0.2, -0.15, 0, 0.15, 0.2, 0.1, 0]
        for i, off in enumerate(seq):
            out = s.feed_metrics(off, ts=i * 0.2)
        self.assertTrue(out["passed"]); self.assertFalse(out["failed"])

    def test_static_photo_fails_timeout(self):
        s = LivenessSession(timeout_sec=3)
        out = {}
        for i in range(40):
            out = s.feed_metrics(0.0, ts=i * 0.2)   # 정지(사진) — 스윙 없음
        self.assertFalse(out["passed"]); self.assertTrue(out["failed"])

    def test_one_side_only_not_enough(self):
        s = LivenessSession()
        for i in range(10):
            out = s.feed_metrics(-0.25, ts=i * 0.2)  # 한쪽만(고정 사진을 기울인 경우)
        self.assertFalse(out["passed"])               # 양극 스윙 아님

    def test_pulse_required_blocks_until_detected(self):
        s = LivenessSession(require_pulse=True)
        seq = [-0.2, 0.2, -0.2, 0.2]
        for i, off in enumerate(seq):
            out = s.feed_metrics(off, ts=i * 0.2)
        self.assertFalse(out["passed"])               # 동작은 됐지만 맥박 없음
        s._pulse = True
        out = s.feed_metrics(0.0, ts=2.0)
        self.assertTrue(out["passed"])                # 맥박 감지되면 통과


if __name__ == "__main__":
    unittest.main()
