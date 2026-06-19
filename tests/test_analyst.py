"""Analyst 가산식 판단 테스트 (§14: 규칙·낙상·PPE 반응 + 폴백/딥러닝 가산)"""
import sys
import unittest
from pathlib import Path

# vigent-core 를 임포트 경로에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import vision_loader  # noqa: E402
from agents.analyst import AnalystAgent  # noqa: E402


class TestAnalyst(unittest.TestCase):
    def setUp(self):
        cfg = vision_loader.load_vision("safety")
        self.analyst = AnalystAgent(cfg)

    def test_safe_when_no_signal(self):
        r = self.analyst.judge({})
        self.assertEqual(r["level"], "safe")
        self.assertEqual(r["score"], 0)

    def test_zone_intrusion_high(self):
        r = self.analyst.judge({"zone_intrusion": True})
        self.assertEqual(r["level"], "high")        # severity high=60
        self.assertTrue(any(f["rule"] == "zone_intrusion" for f in r["fired"]))

    def test_ppe_missing_medium(self):
        r = self.analyst.judge({"ppe_missing": True})
        self.assertEqual(r["level"], "medium")      # severity medium=30

    def test_fall_by_torso_angle_heuristic(self):
        # 딥러닝 신호 없이 몸통각만으로 낙상 의심(휴리스틱 폴백)
        r = self.analyst.judge({"torso_angle": 75})
        self.assertEqual(r["level"], "high")
        self.assertTrue(r["fallback"])
        self.assertFalse(r["used_dl"])

    def test_guard_bypass_critical(self):
        r = self.analyst.judge({"hand_in_machine_zone": True})
        self.assertEqual(r["level"], "critical")    # severity critical=100

    def test_dl_additive_increases_score(self):
        # 같은 규칙이라도 딥러닝 신호가 있으면 점수가 '가산'되어 더 높아진다
        rule_only = self.analyst.judge({"ppe_missing": True})
        with_dl = self.analyst.judge({"ppe_missing": True}, dl={"ppe_conf": 1.0})
        self.assertGreater(with_dl["score"], rule_only["score"])
        self.assertTrue(with_dl["used_dl"])
        self.assertFalse(with_dl["fallback"])

    def test_additive_combination(self):
        # 여러 규칙 동시 발동 → 점수 누적
        r = self.analyst.judge({"zone_intrusion": True, "ppe_missing": True})
        self.assertGreaterEqual(r["score"], 60 + 30)
        self.assertEqual(len(r["fired"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
