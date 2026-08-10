"""[Q-3] 검출 실패 침묵 방지 회귀 테스트.

백엔드 예외가 나면 guard.detect()가 조용히 0건으로 넘어가지 않고: ERROR 로그를 남기고,
연속 PREDICT_FAIL_DEGRADE_THRESHOLD 회 실패하면 slot_degraded 를 세워 status()(/health)에
노출하고, 다음 성공 호출에서 복구(INFO 로그 + 플래그 해제)되는지 검증한다."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402

_FAKE_IMG = np.zeros((10, 10, 3), dtype=np.uint8)


class _FlakyModel:
    """처음 n_fail 회는 예외, 그 뒤로는 성공(빈 목록 반환)."""

    def __init__(self, n_fail: int):
        self.n_fail = n_fail
        self.calls = 0

    def detect(self, image_bgr, conf=0.0, imgsz=None, augment=False):
        self.calls += 1
        if self.calls <= self.n_fail:
            raise RuntimeError(f"boom #{self.calls}")
        return []


def _guard(n_fail: int) -> guard_mod.GuardAgent:
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
    g._models = {"person": _FlakyModel(n_fail)}
    g._slot_path = {}
    g._load_errors = {}
    g._predict_fail_streak = {}
    g._slot_degraded = {}
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.HYSTERESIS = dict(g.HYSTERESIS_FRAMES)
    g._sig_streak = {}
    g.PERSON_ENSEMBLE = True
    return g


class SlotDegraded(unittest.TestCase):
    def test_error_logged_on_each_failure(self):
        g = _guard(n_fail=10)
        with self.assertLogs("vigent.guard", level="ERROR") as cm:
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:err")
        self.assertTrue(any("검출 실패" in line for line in cm.output),
                         f"실패 시 ERROR 로그 없음: {cm.output}")

    def test_degraded_after_threshold_consecutive_failures(self):
        g = _guard(n_fail=10)
        self.assertEqual(g.PREDICT_FAIL_DEGRADE_THRESHOLD, 3, "테스트가 가정하는 임계값과 다름")
        with self.assertLogs("vigent.guard", level="ERROR"):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:deg")   # 1회째
        self.assertNotIn("person", {k for k, v in g._slot_degraded.items() if v},
                          "1회 실패만으로 DEGRADED 되면 안 됨(과민반응)")
        with self.assertLogs("vigent.guard", level="ERROR"):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:deg")   # 2회째
        with self.assertLogs("vigent.guard", level="ERROR") as cm:
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:deg")   # 3회째 — 임계 도달
        self.assertTrue(g._slot_degraded.get("person"), "연속 3회 실패했는데 DEGRADED 안 됨")
        self.assertTrue(any("DEGRADED" in line for line in cm.output))
        status = g.status()
        self.assertEqual(status["slot_degraded"], {"person": True}, "status()/health 에 노출 안 됨")
        self.assertEqual(status["predict_fail_streak"].get("person"), 3)

    def test_recovers_after_success(self):
        g = _guard(n_fail=3)   # 3번 실패 후 4번째부터 성공
        for _ in range(3):
            with self.assertLogs("vigent.guard", level="ERROR"):
                g.detect(_FAKE_IMG, detectors=["person"], track_key="t:rec")
        self.assertTrue(g._slot_degraded.get("person"))
        with self.assertLogs("vigent.guard", level="INFO") as cm:
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:rec")   # 4번째 — 성공
        self.assertFalse(g._slot_degraded.get("person"), "성공 호출 후에도 DEGRADED 안 풀림")
        self.assertEqual(g._predict_fail_streak.get("person"), 0)
        self.assertTrue(any("복구" in line for line in cm.output), f"복구 로그 없음: {cm.output}")
        self.assertEqual(g.status()["slot_degraded"], {}, "복구 후 status()에 계속 남아있음")

    def test_intermittent_failure_does_not_falsely_degrade(self):
        """연속이 아니라 성공/실패가 섞이면(예: 1회 실패 후 성공) 스트릭이 리셋돼 DEGRADED 안 됨."""
        class _AlternatingModel:
            def __init__(self):
                self.calls = 0

            def detect(self, image_bgr, conf=0.0, imgsz=None, augment=False):
                self.calls += 1
                if self.calls % 2 == 1:   # 홀수 호출만 실패
                    raise RuntimeError("boom")
                return []

        g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
        g._models = {"person": _AlternatingModel()}
        g._slot_path = {}
        g._load_errors = {}
        g._predict_fail_streak = {}
        g._slot_degraded = {}
        g._tracks_by_key = {}
        g._bytetrack_by_key = {}
        g._key_last_used = {}
        g._last_sweep_at = 0.0
        g._tid_seq = 0
        g.HYSTERESIS = dict(g.HYSTERESIS_FRAMES)
        g._sig_streak = {}
        g.PERSON_ENSEMBLE = True

        for _ in range(6):
            with mock.patch.object(guard_mod, "_guard_logger", wraps=guard_mod._guard_logger):
                g.detect(_FAKE_IMG, detectors=["person"], track_key="t:alt")
        self.assertFalse(g._slot_degraded.get("person"),
                          "실패가 연속이 아니라 교대로 났는데 DEGRADED 됨(스트릭 리셋 안 됨)")


if __name__ == "__main__":
    unittest.main()
