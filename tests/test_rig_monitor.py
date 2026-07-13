"""RIG 상태기계(rig_monitor) 검증 — 정상 절차 전이 + ALARM (a)/(b)/(c) 시나리오.

설계 확정본(줄걸이 작업 절차): IDLE→WORKING→LIFT_CHECK→CLEAR→HOISTING,
예외→ALARM (a)미이탈+임계높이초과 (b)낙상 (c)인양중 신규진입.
※ 합성 obs = 상태기계 로직 검증. 실제 영상 정합은 별도(사용자 육안 확인).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

from rig_monitor import RigStateMachine, RigConfig, ALARM, HOISTING  # noqa: E402

DT = 0.1


def _phase(t0, t1, **f):
    out, t = [], t0
    while t < t1 - 1e-9:
        o = {"t": round(t, 3)}
        o.update(f)
        out.append(o)
        t += DT
    return out


def _run(stream, cfg=None):
    m = RigStateMachine(cfg=cfg or RigConfig())
    seen, t_alarm = [], None
    for o in stream:
        r = m.update(o)
        seen.append(r["state"])
        if r["alarm"] and t_alarm is None:
            t_alarm = r["t"]
    return m, seen, t_alarm


class TestRigMonitor(unittest.TestCase):
    def test_a_accident_alarm(self):
        """(a) 미동권상 후 작업자 미이탈 상태로 하물이 임계높이 초과 → ALARM."""
        s = _phase(0.0, 1.5, n_in=2, ids_in=[1, 2], load_h=0.0)
        s += _phase(1.5, 2.5, n_in=2, ids_in=[1, 2], load_h=0.15)   # 미동권상
        t = 2.5
        while t < 4.6:                                              # 미이탈 상태 상승
            s.append({"t": round(t, 3), "n_in": 2, "ids_in": [1, 2],
                      "load_h": round(0.15 + (t - 2.5) * 0.30, 3)})
            t += DT
        m, seen, t_alarm = _run(s)
        self.assertIn("WORKING", seen)
        self.assertIn("LIFT_CHECK", seen)
        self.assertEqual(m.state, ALARM)
        self.assertIsNotNone(t_alarm)
        self.assertIn("(a)", m.alarm_reason)

    def test_safe_no_alarm(self):
        """작업자 이탈 확인 후 본 인양 → CLEAR→HOISTING, 경보 없음."""
        s = _phase(0.0, 1.5, n_in=2, ids_in=[1, 2], load_h=0.0)
        s += _phase(1.5, 2.7, n_in=2, ids_in=[1, 2], load_h=0.15)
        s += _phase(2.7, 4.0, n_in=0, ids_in=[], load_h=0.15)       # 이탈
        s += _phase(4.0, 5.5, n_in=0, ids_in=[], load_h=0.60)       # 본 인양
        m, seen, t_alarm = _run(s)
        self.assertIn(HOISTING, seen)
        self.assertNotIn(ALARM, seen)
        self.assertIsNone(t_alarm)

    def test_c_new_person_during_hoist(self):
        """(c) HOISTING 중 신규 인물 반경 진입 → ALARM."""
        s = _phase(0.0, 1.5, n_in=2, ids_in=[1, 2], load_h=0.0)
        s += _phase(1.5, 2.7, n_in=2, ids_in=[1, 2], load_h=0.15)
        s += _phase(2.7, 4.0, n_in=0, ids_in=[], load_h=0.15)
        s += _phase(4.0, 5.0, n_in=0, ids_in=[], load_h=0.60)       # HOISTING
        s += _phase(5.0, 6.0, n_in=1, ids_in=[9], load_h=0.60)      # 신규 진입
        m, seen, t_alarm = _run(s)
        self.assertEqual(m.state, ALARM)
        self.assertIn("(c)", m.alarm_reason)

    def test_b_fall_alarm(self):
        """(b) 반경 내 낙상 → ALARM."""
        s = _phase(0.0, 1.5, n_in=2, ids_in=[1, 2], load_h=0.0)
        s += _phase(1.5, 3.0, n_in=2, ids_in=[1, 2], load_h=0.0, fall=True)
        m, seen, t_alarm = _run(s)
        self.assertEqual(m.state, ALARM)
        self.assertIn("(b)", m.alarm_reason)

    def test_config_threshold_externalized(self):
        """임계높이 외부화 확인 — alarm_height_m 를 높이면 같은 시나리오서 (a) 미발화."""
        s = _phase(0.0, 1.5, n_in=2, ids_in=[1, 2], load_h=0.0)
        s += _phase(1.5, 2.5, n_in=2, ids_in=[1, 2], load_h=0.15)
        s += _phase(2.5, 4.0, n_in=2, ids_in=[1, 2], load_h=0.28)   # 0.30 미만 유지
        m, seen, t_alarm = _run(s, cfg=RigConfig(alarm_height_m=0.30))
        self.assertNotIn(ALARM, seen)                               # 0.28<0.30 → 미발화


if __name__ == "__main__":
    unittest.main()
