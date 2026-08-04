"""2.2 ① 속도 적응형 EMA(_adaptive_ema) 회귀 — 저속=EMA_MIN(현행), 고속=EMA_MAX(raw)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
from agents.guard import GuardAgent  # noqa: E402


class _Stub:
    EMA_MIN = 0.75
    EMA_MAX = 1.0
    EMA_DREF = 0.25


class TestAdaptiveEma(unittest.TestCase):
    def _a(self, old, new):
        return GuardAgent._adaptive_ema(_Stub(), old, new)

    def test_no_move_is_ema_min(self):
        b = [0.4, 0.4, 0.6, 0.6]
        self.assertAlmostEqual(self._a(b, b), 0.75, places=6)   # 이동 0 → 현행 평활 유지(저하0)

    def test_large_move_is_ema_max(self):
        old = [0.4, 0.4, 0.6, 0.6]
        new = [0.7, 0.4, 0.9, 0.6]   # 중심 0.3 이동, 대각선~0.28 → d/dref >> 1 → 캡 EMA_MAX
        self.assertAlmostEqual(self._a(old, new), 1.0, places=6)

    def test_mid_between(self):
        old = [0.4, 0.4, 0.6, 0.6]
        diag = ((0.2) ** 2 + (0.2) ** 2) ** 0.5          # 박스 대각선
        shift = 0.25 * diag * 0.5                          # d = dref 의 절반 → a 중간값
        new = [0.4 + shift, 0.4, 0.6 + shift, 0.6]
        a = self._a(old, new)
        self.assertTrue(0.75 < a < 1.0)


if __name__ == "__main__":
    unittest.main()
