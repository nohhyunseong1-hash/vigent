"""[B3] 검출 기아 2차 방어 테스트.

원인(audit/b3_root_cause_2026-08-16.md): 카메라 동시 세션 한도 2(실측) · 워커 1 + go2rtc 1 =
여유 0 → 슬롯 경쟁에서 워커가 영구히 밀려 "영상은 살고 검출만 죽는" 상태가 된다.
여기서는 단계별 승격(슬롯 회수 → 워커 재시작 → 프로세스 재기동)이 **시간 조건대로** 동작하는지,
그리고 회복 시 카운터가 초기화되는지 검증한다.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import health_status  # noqa: E402
import starvation_guard as sg  # noqa: E402


def _stale(detect_age=400.0, frame_age=0.5):
    """stale_detect(=P0 지문) 상태의 워커 status."""
    return {"running": True, "uptime_s": 900.0,
            "last_frame_secs_ago": frame_age, "last_detect_secs_ago": detect_age,
            "last_detect_ms": None, "session_generation": 2, "dropped_frames": 0,
            "reconnects": 1, "hangs": 0}


def _ok():
    return {"running": True, "uptime_s": 900.0,
            "last_frame_secs_ago": 0.4, "last_detect_secs_ago": 0.9,
            "last_detect_ms": 110.0, "session_generation": 1, "dropped_frames": 0,
            "reconnects": 0, "hangs": 0}


class TestEscalation(unittest.TestCase):
    def setUp(self):
        sg._state.clear()

    def _tick_with(self, cams):
        fake_worker = mock.MagicMock()
        fake_worker.manager.status.return_value = {"cameras": cams}
        with mock.patch.dict(sys.modules, {"worker": fake_worker}):
            sg._tick()

    def test_healthy_camera_does_not_arm(self):
        self._tick_with({"c1": _ok()})
        self.assertEqual(sg._state, {})

    def test_stale_arms_but_does_not_act_immediately(self):
        """감지 즉시 슬롯을 뺏으면 일시적 흔들림에도 확대뷰가 끊긴다 — 유예가 있어야 한다."""
        with mock.patch.object(sg, "_release_go2rtc_slot") as rel:
            self._tick_with({"c1": _stale()})
            rel.assert_not_called()
        self.assertIn("c1", sg._state)
        self.assertFalse(sg._state["c1"]["grabbed"])

    def test_grab_slot_after_grace(self):
        """1단계: starve_grab_s 경과 → go2rtc 슬롯 회수(안전 검출 > 라이브 영상)."""
        with mock.patch.object(sg, "_release_go2rtc_slot") as rel:
            self._tick_with({"c1": _stale()})
            sg._state["c1"]["since"] = time.time() - (sg._GRAB_S + 1)
            self._tick_with({"c1": _stale()})
            rel.assert_called_once_with("c1")
        self.assertTrue(sg._state["c1"]["grabbed"])

    def test_restart_worker_after_longer_stall(self):
        """2단계: 슬롯 회수로도 안 살아나면 해당 카메라 워커만 재시작."""
        with mock.patch.object(sg, "_release_go2rtc_slot"), \
             mock.patch.object(sg, "_restart_worker") as rst:
            self._tick_with({"c1": _stale()})
            sg._state["c1"].update(since=time.time() - (sg._RESTART_S + 1), grabbed=True)
            self._tick_with({"c1": _stale()})
            rst.assert_called_once_with("c1")

    def test_escalate_after_max_fails(self):
        """3단계: 반복 실패 → 프로세스 재기동 승격."""
        with mock.patch.object(sg, "_release_go2rtc_slot"), \
             mock.patch.object(sg, "_restart_worker"), \
             mock.patch.object(sg, "_escalate") as esc:
            self._tick_with({"c1": _stale()})
            sg._state["c1"].update(since=time.time() - (sg._RESTART_S + 1), grabbed=True,
                                   restarts=sg._MAX_FAILS - 1)
            self._tick_with({"c1": _stale()})
            esc.assert_called_once()

    def test_recovery_clears_state(self):
        """검출이 살아나면 카운터가 초기화돼 다음 사건이 처음부터 판정된다."""
        self._tick_with({"c1": _stale()})
        self.assertIn("c1", sg._state)
        self._tick_with({"c1": _ok()})
        self.assertNotIn("c1", sg._state)

    def test_stale_frame_is_not_starvation(self):
        """프레임 자체가 끊긴 건(카메라 전원 off) 슬롯 기아가 아니다 — 슬롯을 뺏어봐야 소용없다."""
        st = _stale(detect_age=400.0, frame_age=400.0)
        self.assertEqual(health_status.camera_status(st)["status"], health_status.STALE_FRAME)
        with mock.patch.object(sg, "_release_go2rtc_slot") as rel:
            self._tick_with({"c1": st})
            rel.assert_not_called()
        self.assertNotIn("c1", sg._state)


class TestConfigWiring(unittest.TestCase):
    def test_stability_vars_have_real_consumers(self):
        """STABILITY.md 가 문서로만 설명하던 2차 워치독 설정 3종이 실제로 소비된다.

        문서만 있고 코드에 소비처가 없는 설정은 '없는 기능'이다(감사 §7 불일치 항목)."""
        self.assertGreater(sg._RESTART_S, 0)     # VIGENT_HANG_RESTART_S
        self.assertGreater(sg._MAX_FAILS, 0)     # VIGENT_HEALTH_FAILS
        self.assertIsInstance(sg._RESTART_CMD, str)   # VIGENT_RESTART_CMD

    def test_reconnect_backoff_cap_lowered(self):
        """백오프 상한 30→5초: 슬롯이 열려도 못 잡던 구조를 깨는 1차 방어."""
        import worker
        self.assertLessEqual(worker._RECONNECT_MAX, 10.0)


if __name__ == "__main__":
    unittest.main()
