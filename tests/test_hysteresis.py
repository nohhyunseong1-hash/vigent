"""Phase C item2 신호 히스테리시스(_hysteresis) 회귀 — 연속 N프레임 확인 후 발화.

N=1=현행(즉시), N=2=1프레임 완충. 하강(raw=False)은 즉시 리셋. track_key 별 독립.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
from agents.guard import GuardAgent  # noqa: E402


class _Stub:
    """모델 로드 없이 _hysteresis 로직만 시험(HYSTERESIS·_sig_streak 만 필요)."""
    def __init__(self, hyst):
        self.HYSTERESIS = hyst
        self._sig_streak: dict = {}


class TestHysteresis(unittest.TestCase):
    def _h(self, stub, key, name, raw):
        return GuardAgent._hysteresis(stub, key, name, raw)

    def test_n2_needs_two_consecutive(self):
        s = _Stub({"fire_smoke": 2})
        self.assertFalse(self._h(s, "cam", "fire_smoke", True))   # 1프레임 → 아직
        self.assertTrue(self._h(s, "cam", "fire_smoke", True))    # 2프레임 연속 → 발화
        self.assertTrue(self._h(s, "cam", "fire_smoke", True))    # 유지
        self.assertFalse(self._h(s, "cam", "fire_smoke", False))  # 하강 즉시 리셋
        self.assertFalse(self._h(s, "cam", "fire_smoke", True))   # 다시 1프레임

    def test_n1_is_immediate(self):
        s = _Stub({"ppe_missing": 1})
        self.assertTrue(self._h(s, "cam", "ppe_missing", True))   # N=1 → 즉시(현행과 동일)

    def test_per_track_key_independent(self):
        s = _Stub({"fire_smoke": 2})
        self.assertFalse(self._h(s, "A", "fire_smoke", True))     # A 1프레임
        self.assertFalse(self._h(s, "B", "fire_smoke", True))     # B 1프레임(A 와 독립)
        self.assertTrue(self._h(s, "A", "fire_smoke", True))      # A 2프레임 → 발화
        self.assertFalse(self._h(s, "B", "fire_smoke", False))    # B 는 리셋


if __name__ == "__main__":
    unittest.main()
