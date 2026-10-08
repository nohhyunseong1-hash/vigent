"""CODE_AUDIT_20260928 #2 — 릴레이(사이렌) 종료·실패 경로. [2026-09-28]

★무엇을 고정하는가
  ① OFF 최종 실패 → off_failed + 지수 백오프 재시도 예약(off_retry_count/off_retry_in_s 노출) → 서버가 살아나면 OFF 성공·플래그 해제. 첫 실패는 통보 1회.
  ② HTTP 는 락 밖: OFF 재시도가 오래 걸려도 다른 스레드의 turn_on 이 막히지 않는다.
  ③ _shutdown 은 릴레이가 ON(또는 off_failed)이면 가장 먼저 turn_off 를 부른다. 꺼져 있으면 부르지 않는다.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402  [OPEN_ISSUES #3] 운영 큐 격리


def _cfg(**kw):
    base = {"enabled": True, "url": "http://127.0.0.1:1/x", "method": "GET", "on_duration_s": 30.0, "on_attempts": 1, "off_attempts": 1,
            "timeout_s": 0.2, "off_timeout_s": 0.2, "backoff_cap_s": 0.01, "off_retry_base_s": 0.05, "off_retry_cap_s": 0.2}
    base.update(kw)
    return mock.patch.object(relay, "_cfg", side_effect=lambda k, d: base.get(k, d))


class OffFailureRetriesWithBackoff(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        relay._reset_for_test(); self.addCleanup(relay._reset_for_test)

    def test_retry_until_success_and_notify_once(self):
        fails = {"n": 0}

        def http(action, timeout):
            if action == "on":
                return True, "HTTP 200"
            fails["n"] += 1
            return (True, "HTTP 200") if fails["n"] >= 3 else (False, "timeout")
        submitted = []
        with _cfg(), mock.patch.object(relay, "enabled", return_value=True), mock.patch.object(relay, "_http", side_effect=http), \
             mock.patch("alert_notify.submit", side_effect=lambda **k: submitted.append(k) or {"queued": True}):
            self.assertTrue(relay.turn_on("t")["sent"])
            r = relay.turn_off("t")
            self.assertFalse(r["sent"])
            st = relay.status(); self.assertTrue(st["off_failed"]); self.assertEqual(st["off_retry_count"], 1); self.assertIsNotNone(st["off_retry_in_s"])
            self.assertEqual(relay._off_retry_delay(0), 0.05); self.assertEqual(relay._off_retry_delay(3), 0.2)   # cap
            for _ in range(60):
                if not relay.status()["off_failed"]:
                    break
                time.sleep(0.05)
        st = relay.status()
        self.assertFalse(st["off_failed"]); self.assertFalse(st["on"]); self.assertEqual(st["off_retry_count"], 0); self.assertIsNone(st["off_retry_in_s"])
        self.assertEqual(fails["n"], 3, "1회 실패 + 재시도 2회(두 번째 성공)")
        self.assertEqual(len(submitted), 1, "첫 실패 때만 통보"); self.assertEqual(submitted[0]["rule"], "relay_off_failed"); self.assertEqual(submitted[0]["cam"], "relay")


class HttpOutsideLock(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        relay._reset_for_test(); self.addCleanup(relay._reset_for_test)

    def test_turn_on_not_blocked_by_slow_off(self):
        gate = threading.Event()

        def http(action, timeout):
            if action == "off":
                gate.wait(5.0)
                return True, "HTTP 200"
            return True, "HTTP 200"
        with _cfg(off_attempts=1), mock.patch.object(relay, "enabled", return_value=True), mock.patch.object(relay, "_http", side_effect=http):
            relay.turn_on("t")
            th = threading.Thread(target=lambda: relay.turn_off("slow")); th.start()
            time.sleep(0.1)                                  # OFF 가 HTTP 안에서 대기 중
            t0 = time.time(); r = relay.turn_on("while-off"); dt = time.time() - t0
            gate.set(); th.join(5.0)
        self.assertTrue(r["sent"]); self.assertLess(dt, 1.0, f"turn_on 이 OFF HTTP 뒤에서 {dt:.2f}s 막혔다")


class ShutdownTurnsRelayOffFirst(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())

    def test_shutdown_calls_turn_off_when_on(self):
        import main
        order: list[str] = []
        with mock.patch.object(relay, "status", return_value={"enabled": True, "on": True, "off_failed": False}), \
             mock.patch.object(relay, "turn_off", side_effect=lambda r="": order.append("relay_off") or {"sent": True, "reason": "HTTP 200"}), \
             mock.patch("worker.manager.stop_all", side_effect=lambda: order.append("workers") or "0"), \
             mock.patch.object(main._cameras_router, "stop_go2rtc", side_effect=lambda: order.append("go2rtc")), \
             mock.patch("alert_notify.stop"), mock.patch("alert_queue.stop"), mock.patch("retention_scheduler.stop"), mock.patch("starvation_guard.stop"):
            main._shutdown()
        self.assertEqual(order[:2], ["relay_off", "workers"])

    def test_shutdown_skips_relay_when_off(self):
        import main
        with mock.patch.object(relay, "status", return_value={"enabled": True, "on": False, "off_failed": False}), \
             mock.patch.object(relay, "turn_off") as off, \
             mock.patch("worker.manager.stop_all", return_value="0"), mock.patch.object(main._cameras_router, "stop_go2rtc"), \
             mock.patch("alert_notify.stop"), mock.patch("alert_queue.stop"), mock.patch("retention_scheduler.stop"), mock.patch("starvation_guard.stop"):
            main._shutdown()
        off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
