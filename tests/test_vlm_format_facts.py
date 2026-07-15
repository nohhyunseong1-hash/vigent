"""P1-5 후속 회귀 — vlm_risk_summary.format_facts 실행 증명.

F821(`Any` 미정의) 수정 검증: format_facts 는 `persons: list[Any]` annotation 을 포함한다.
이 경로가 실제로 실행되어 정상 문자열을 만드는지(NameError 없이) 확인한다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core" / "ml"))

from vlm_risk_summary import format_facts  # noqa: E402


class TestFormatFacts(unittest.TestCase):
    def test_runs_and_returns_text(self):
        """탐지 있음 → 사람 명수 + 기타 라벨 문자열(예외 없이)."""
        out = format_facts([{"label": "person", "conf": 0.9},
                            {"label": "forklift", "conf": 0.8}])
        self.assertIsInstance(out, str)
        self.assertIn("사람", out)
        self.assertIn("forklift", out)

    def test_empty_returns_empty(self):
        self.assertEqual(format_facts([]), "")
        self.assertEqual(format_facts(None), "")

    def test_danger_zone_flag(self):
        """in_danger_zone=True 경로도 예외 없이 실행."""
        out = format_facts([{"label": "person", "conf": 0.95}], in_danger_zone=True)
        self.assertIsInstance(out, str)
        self.assertIn("사람", out)


if __name__ == "__main__":
    unittest.main()
