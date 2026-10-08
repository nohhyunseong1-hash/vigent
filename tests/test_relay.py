"""[P3a/P3b] 물리 출력 릴레이 테스트 — mock 서버로 ON/OFF 시퀀스 검증.

배경(감사 🟠C7): `safety_relay_signal` 이 **로그 항목만 추가**하고 sent:True 를 반환했다 —
현장에서 "경보가 울렸다"고 표시되는데 아무 소리도 안 나는 상태였다.

★검증의 중심은 **OFF 보장**이다. 사이렌이 안 켜지는 것보다 **안 꺼지는 것이 최악**이다.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402  [OPEN_ISSUES #3] 운영 큐 격리
from mock_relay import MockRelay  # noqa: E402


class _RelayTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        # ★[2026-08-28] 다른 테스트가 띄워둔 **배경 전송 스레드를 먼저 재운다.**
        #   alert_notify 전송 스레드와 alert_queue 재시도 스레드는 dispatcher 를 거쳐
        #   `relay.turn_on()` 까지 닿는다. 그 스레드가 이 테스트 도중 깨어나면 전역 릴레이
        #   상태(on_count·retrigger_count)를 건드려 **전체 스위트에서만** 실패한다
        #   (실측: retrigger_count 가 1 이 아니라 2, 단독 실행은 3/3 통과).
        #   [F29] 와 같은 계열 — 간헐 실패는 진짜 회귀와 구분이 안 돼 게이트를 못 믿게 만든다.
        for _mod in ("alert_notify", "alert_queue"):
            try:
                __import__(_mod).stop()
            except Exception:  # noqa: BLE001  없거나 안 돌고 있으면 그만이다
                pass
        self.m = MockRelay().start()
        relay._reset_for_test()

    def tearDown(self):
        relay._reset_for_test()
        self.m.stop()

    def _cfg(self, **kw):
        base = {"enabled": True, "url": self.m.url, "method": "GET",
                "on_duration_s": 30.0, "on_attempts": 3, "off_attempts": 8,
                "timeout_s": 2.0, "off_timeout_s": 2.0, "backoff_cap_s": 0.01}
        base.update(kw)
        return mock.patch.object(relay, "_cfg", side_effect=lambda k, d: base.get(k, d))


class TestNormalSequence(_RelayTest):
    def test_on_then_off(self):
        """정상 ON → OFF 시퀀스가 릴레이에 그대로 전달된다."""
        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True):
            r1 = relay.turn_on("침입 감지")
            r2 = relay.turn_off("해제")
        self.assertTrue(r1["sent"])
        self.assertTrue(r2["sent"])
        self.assertEqual(self.m.actions(), ["on", "off"])
        self.assertFalse(relay.status()["on"])

    def test_disabled_does_nothing(self):
        """relay.enabled=false(기본)면 아무 요청도 보내지 않는다."""
        with self._cfg(enabled=False), mock.patch.object(relay, "enabled", return_value=False):
            r = relay.turn_on("x")
        self.assertFalse(r["sent"])
        self.assertEqual(self.m.actions(), [])

    def test_status_shape(self):
        s = relay.status()
        for k in ("enabled", "on", "off_failed", "on_count", "off_count", "retrigger_count"):
            self.assertIn(k, s)


class TestRetryAndRecovery(_RelayTest):
    def test_on_retries_until_server_recovers(self):
        """ON 중 서버가 5xx 를 내다 복구되면 재시도로 성공한다."""
        self.m.fail_status = 500
        calls = {"n": 0}
        orig = relay._http

        def flaky(action, timeout):
            calls["n"] += 1
            if calls["n"] >= 2:
                self.m.fail_status = None       # 2번째 시도부터 복구
            return orig(action, timeout)

        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True), \
             mock.patch.object(relay, "_http", side_effect=flaky):
            r = relay.turn_on("재시도")
        self.assertTrue(r["sent"], "재시도로 복구되지 않았다")
        self.assertIn("on", self.m.actions())

    def test_off_retries_more_than_on(self):
        """★OFF 는 ON 보다 재시도 횟수가 많아야 한다(안 꺼지는 것이 최악)."""
        seen = {"on": 0, "off": 0}

        def counting(action, timeout):
            seen[action] += 1
            return False, "주입 실패"

        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True), \
             mock.patch.object(relay, "_http", side_effect=counting):
            relay.turn_on("x")
            relay.turn_off("x")
        self.assertGreater(seen["off"], seen["on"],
                           f"OFF 재시도({seen['off']})가 ON({seen['on']})보다 많지 않다")


class TestOffFailureIsVisible(_RelayTest):
    def test_off_failure_sets_flag_and_surfaces(self):
        """★OFF 최종 실패는 상태로 드러나야 한다 — 사이렌이 켜진 채 남았을 수 있다."""
        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True):
            relay.turn_on("경보")
            self.m.down = True                  # 릴레이가 응답하지 않는 상태
            r = relay.turn_off("해제 시도")
        self.assertFalse(r["sent"])
        st = relay.status()
        self.assertTrue(st["off_failed"], "OFF 실패가 상태에 드러나지 않는다")
        self.assertIn("OFF 실패", st["last_error"])

    def test_successful_off_clears_flag(self):
        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True):
            relay.turn_on("경보")
            self.m.down = True
            relay.turn_off("실패")
            self.assertTrue(relay.status()["off_failed"])
            self.m.down = False                 # 릴레이 복구
            relay.turn_off("재시도")
        self.assertFalse(relay.status()["off_failed"], "복구 후에도 실패 플래그가 남아 있다")


class TestRetrigger(_RelayTest):
    def test_duplicate_alert_extends_not_duplicates(self):
        """중복 경보 시 ON 을 다시 보내되 **연장**으로 표시되고 on_count 는 안 늘어난다."""
        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True):
            r1 = relay.turn_on("1차")
            r2 = relay.turn_on("2차")
        self.assertFalse(r1["retrigger"])
        self.assertTrue(r2["retrigger"], "재트리거로 표시되지 않았다")
        st = relay.status()
        self.assertEqual(st["on_count"], 1)          # 새 ON 이 아니라 연장
        self.assertEqual(st["retrigger_count"], 1)

    def test_auto_off_after_duration(self):
        """on_duration_s 뒤 자동 OFF 된다.

        ★[F29, 2026-08-21] 고정 sleep(1.0s) → **조건 폴링**으로 바꿨다. 타이머가 0.3s 에
        발화한 뒤 OFF 요청이 왕복하는데, 전체 스위트 부하에서는 남은 0.7s 여유가 얇아
        아직 on 인 채로 단정되곤 했다(단독 실행은 통과 / 전체 실행은 절반 확률 실패).
        '언제까지 되는가' 가 아니라 '되는가' 를 보는 테스트라 폴링이 맞다.
        """
        with self._cfg(on_duration_s=0.3), mock.patch.object(relay, "enabled", return_value=True):
            relay.turn_on("자동해제 확인")
            self.assertTrue(relay.status()["on"])
            deadline = time.time() + 5.0
            while time.time() < deadline and relay.status()["on"]:
                time.sleep(0.02)
            self.assertFalse(relay.status()["on"], "자동 OFF 가 동작하지 않았다(5초 내)")
        self.assertIn("off", self.m.actions())


class TestHealthIntegration(_RelayTest):
    def test_off_failed_should_degrade(self):
        """OFF 실패 상태는 /health 가 degraded 로 올려야 한다(정상이 아니다).

        여기서는 상태 플래그만 확인한다 — 라우터 연동은 system.py 에서 이 값을 읽는다."""
        with self._cfg(), mock.patch.object(relay, "enabled", return_value=True):
            relay.turn_on("경보")
            self.m.down = True
            relay.turn_off("해제")
        self.assertTrue(relay.status()["off_failed"])


if __name__ == "__main__":
    unittest.main()
