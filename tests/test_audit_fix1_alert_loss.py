"""CODE_AUDIT_20260928 #1 — 경보 경로의 조용한 유실 3곳. [2026-09-28]

★무엇을 고정하는가
  ① 센서 위험 전이는 alert_notify.submit 이 queued=True 를 돌려줄 때만 확정된다. 게이트에 막히면 다음 POST 가 다시 전이로 시도한다.
  ② alert_queue.enqueue 가 실패하면 dispatcher 가 ERROR 로그 + status()["enqueue_fail"] 로 드러낸다(조용히 row_id=None 이 아니다).
  ③ alert_notify.stop() 은 메모리 큐 잔여를 alert_queue.enqueue 로 이월하고 stats["carried_over"] 로 센다.
"""
from __future__ import annotations

import queue
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agents.dispatcher as _d  # noqa: E402
import alert_notify  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class SensorTransitionConfirmedOnlyWhenQueued(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        from routers import safety_core as sc
        self.sc = sc
        sc._SENSOR_DANGER.clear()
        import data_engine
        p = mock.patch.object(data_engine, "log_event", return_value={"evidence": None}); p.start(); self.addCleanup(p.stop)

    def _post(self, value: float):
        return self.sc.safety_sensor({"type": "co", "value": value, "site": "t-sensor"})

    def test_blocked_submit_keeps_transition_pending_then_confirms(self):
        answers = [{"queued": False, "reason": "hourly_cap"}, {"queued": False, "reason": "hourly_cap"}, {"queued": True, "reason": "fire"}]
        with mock.patch.object(alert_notify, "submit", side_effect=lambda **k: answers.pop(0)) as sub:
            r1 = self._post(50); r2 = self._post(50); r3 = self._post(50); r4 = self._post(50)
        self.assertEqual([r["transition"] for r in (r1, r2, r3, r4)], [True, True, True, False], "막힌 동안은 전이가 소비되지 않는다")
        self.assertEqual([r["alert_sent"] for r in (r1, r2, r3, r4)], [False, False, True, False])
        self.assertEqual(sub.call_count, 3, "queued=True 이후에는 재시도하지 않는다")
        self.assertTrue(self.sc._SENSOR_DANGER["co|t-sensor"])

    def test_exception_in_submit_is_logged_and_not_consumed(self):
        with mock.patch.object(alert_notify, "submit", side_effect=RuntimeError("boom")):
            with self.assertLogs("vigent.safety_core", level="ERROR"):
                r = self._post(50)
        self.assertTrue(r["transition"]); self.assertFalse(r["alert_sent"]); self.assertFalse(self.sc._SENSOR_DANGER.get("co|t-sensor", False))

    def test_recovery_resets_state(self):
        with mock.patch.object(alert_notify, "submit", return_value={"queued": True, "reason": "fire"}):
            self._post(50); r = self._post(5)
        self.assertFalse(r["danger"]); self.assertFalse(self.sc._SENSOR_DANGER["co|t-sensor"])


class _Cfg:
    raw = {"dispatch": {"on_severity": {"critical": ["alarm", "manager_call"], "high": ["alarm"], "medium": ["log"]}}}


class EnqueueFailureIsVisible(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        _d.reset_delivery_stats_for_test()
        self.agent = _d.DispatcherAgent(_Cfg())

    def test_enqueue_exception_logged_and_counted(self):
        import alert_queue
        cfg = {"telegram_token": "000000:SECRET-TOKEN-VALUE-abcdefghijklmnop", "telegram_chat": "1", "webhook_url": None,
               "smtp_host": None, "smtp_port": 587, "smtp_user": None, "smtp_pass": None, "email_to": None}
        with mock.patch.object(_d, "notify_cfg", return_value=cfg), \
             mock.patch.object(alert_queue, "enqueue", side_effect=OSError("disk full")), \
             mock.patch.object(self.agent, "_dispatch_now", return_value={"delivered": False, "results": []}):
            with self.assertLogs("vigent.dispatcher", level="ERROR") as cm:
                self.agent.dispatch("critical", "지게차 협착")
            st = self.agent.status()
        self.assertEqual(st["enqueue_fail"], 1); self.assertIsNotNone(st["enqueue_fail_last_ts"])
        self.assertTrue(any("선기록" in m for m in cm.output))
        self.assertNotIn("SECRET-TOKEN", "".join(cm.output))
        _d.reset_delivery_stats_for_test(); self.assertEqual(self.agent.status()["enqueue_fail"], 0)


class StopCarriesOverPending(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        alert_notify.stop(); alert_notify.reset_for_test()

    def test_remaining_items_go_to_durable_queue(self):
        import alert_queue
        alert_notify._q = queue.Queue(maxsize=8)
        for i in range(3):
            alert_notify._q.put(("critical", f"경보 {i}", {"camera": "c", "rule": "r"}))
        with mock.patch.object(alert_queue, "enqueue", return_value=1) as enq:
            alert_notify.stop()
        self.assertEqual(enq.call_count, 3); self.assertEqual(alert_notify.stats()["carried_over"], 3); self.assertEqual(alert_notify._q.qsize(), 0)

    def test_carry_over_failure_is_counted_and_logged(self):
        import alert_queue
        alert_notify._q = queue.Queue(maxsize=8); alert_notify._q.put(("high", "x", {}))
        with mock.patch.object(alert_queue, "enqueue", side_effect=OSError("locked")):
            with self.assertLogs("vigent.alert_notify", level="ERROR"):
                alert_notify.stop()
        self.assertEqual(alert_notify.stats()["carry_over_failed"], 1); self.assertEqual(alert_notify.stats()["carried_over"], 0)


if __name__ == "__main__":
    unittest.main()
