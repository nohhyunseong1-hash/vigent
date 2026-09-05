"""[CODE_REVIEW M2-4] 근골격 부담자세는 **기록 전용(level="low")** — 통보 없음(2026-09 결정).

배경: ErgonomicsTracker 가 한글 등급("중간"/"높음")으로 발화했는데 통보 배선(dispatcher.on_severity)
키는 critical/high/medium 이라 항상 log 전용으로 떨어졌다 — "통보되는 줄 알았는데 안 되는" 구조.
대표 결정(a): 기록 전용을 명시하고 등급을 "low" 로 통일한다(`/safety/posture` 와 동일).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker as W  # noqa: E402


class ErgonomicLevelLow(unittest.TestCase):
    def test_sustained_bad_posture_fires_low(self):
        tr = W.ErgonomicsTracker()
        tr._enabled, tr._hold_sec, tr._corrob = True, 1.0, False
        person = {"centroid": (50.0, 50.0), "kp_xy": np.zeros((17, 2)), "kp_cf": np.ones(17)}
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        with mock.patch.object(W._posemodel, "persons", return_value=[person]), \
                mock.patch.object(tr._erg, "assess",
                                  return_value={"grades": {"trunk": "bad"}, "note": "허리 60°", "level": "높음"}):
            out = []
            # ts=0.0 은 _MIN_INTERVAL 스로틀(초기 _last_ts=0.0)에 걸려 건너뛰므로 10초부터 시작
            for ts in (10.0, 10.6, 11.2):
                out = tr.update(frame, ts, [[0, 0, 10, 10]])
        self.assertEqual(len(out), 1, f"지속 확정 발화가 없다: {out}")
        rule, level, note = out[0]
        self.assertEqual(rule, "ergonomic_risk")
        self.assertEqual(level, "low", f"근골격은 기록 전용(low)이어야 한다: {level!r}")
        self.assertIn("초 지속", note)

    def test_level_is_english_for_dispatcher(self):
        """한글 등급은 dispatcher.on_severity 어느 키에도 안 걸린다 — 재발 방지."""
        import vision_loader
        from agents import build_agents
        d = build_agents(vision_loader.load_vision("safety"))["Dispatcher"]
        self.assertFalse(d._queue_enabled("low"), "low 는 원격 통보 큐에 들어가면 안 된다(기록 전용)")


if __name__ == "__main__":
    unittest.main()
