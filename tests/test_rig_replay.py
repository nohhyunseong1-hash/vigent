"""rig_replay 어댑터 테스트 (B4) — CSV 파싱·보간·계단 + 재생 시나리오.

수동 주석 obs 를 프레임 obs 로 변환하는 로직과, 변환된 obs 가 rig_monitor 를
기대대로 구동하는지(정상 사이클=무경보 / (a) 미이탈+임계높이=ALARM)를 검증한다.
※ rig_monitor 상태기계 자체의 단위검증은 test_rig_monitor.py.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import rig_replay  # noqa: E402


class TestBuildObs(unittest.TestCase):
    def test_csv_parse_blank_load_h_is_none(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("t,load_h,n_in,fall,note\n0,,1,0,결속\n2,0.15,1,1,권상\n")
            p = f.name
        rows = rig_replay.load_obs_csv(p)
        Path(p).unlink()
        self.assertIsNone(rows[0]["load_h"])
        self.assertEqual(rows[1]["load_h"], 0.15)
        self.assertTrue(rows[1]["fall"])
        self.assertEqual(rows[0]["n_in"], 1)

    def test_interp_linear(self):
        rows = [{"t": 0.0, "load_h": 0.0, "n_in": 1, "fall": False, "note": ""},
                {"t": 2.0, "load_h": 0.20, "n_in": 1, "fall": False, "note": ""}]
        self.assertAlmostEqual(rig_replay._interp_load_h(rows, 1.0), 0.10)

    def test_interp_none_segment(self):
        rows = [{"t": 0.0, "load_h": None, "n_in": 1, "fall": False, "note": ""},
                {"t": 2.0, "load_h": 0.20, "n_in": 1, "fall": False, "note": ""}]
        self.assertIsNone(rig_replay._interp_load_h(rows, 1.0))

    def test_step_hold_n_in(self):
        rows = [{"t": 0.0, "load_h": 0.0, "n_in": 2, "fall": False, "note": ""},
                {"t": 5.0, "load_h": 0.0, "n_in": 0, "fall": False, "note": ""}]
        obs = rig_replay.build_frame_obs(rows, fps=10)
        self.assertEqual(obs[0]["n_in"], 2)
        self.assertEqual(obs[-1]["n_in"], 0)


class TestReplayScenarios(unittest.TestCase):
    def test_alarm_a_hoist_without_clearance(self):
        # 작업자 미이탈(n_in=1) 상태에서 하물이 임계(0.30m) 초과 상승 → ALARM (a)
        rows = [{"t": 0.0, "load_h": 0.0, "n_in": 1, "fall": False, "note": "결속"},
                {"t": 2.0, "load_h": 0.15, "n_in": 1, "fall": False, "note": "미동권상"},
                {"t": 4.0, "load_h": 0.40, "n_in": 1, "fall": False, "note": "미이탈 상승"}]
        res = rig_replay.replay(rows, fps=10)
        self.assertTrue(res["alarms"], "ALARM 이 발생해야 함")
        self.assertIn("(a)", res["alarms"][0]["reason"])

    def test_normal_cycle_no_alarm(self):
        # 작업자 이탈 후 본인양 → 경보 없음
        rows = [{"t": 0.0, "load_h": 0.0, "n_in": 1, "fall": False, "note": "결속"},
                {"t": 2.0, "load_h": 0.15, "n_in": 1, "fall": False, "note": "미동권상"},
                {"t": 4.0, "load_h": 0.15, "n_in": 0, "fall": False, "note": "이탈 확인"},
                {"t": 6.0, "load_h": 0.50, "n_in": 0, "fall": False, "note": "본인양"}]
        res = rig_replay.replay(rows, fps=10)
        self.assertEqual(res["alarms"], [], "정상 절차는 무경보여야 함")
        self.assertIn(res["final_state"], ("HOISTING", "CLEAR"))


if __name__ == "__main__":
    unittest.main()
