"""[CODE_REVIEW M4-4] 재시도 경로는 원격 채널만 다시 보낸다 — relay(사이렌)·log 는 재트리거하지 않는다.

배경: alert_queue 재시도가 dispatcher._dispatch_now 를 그대로 불러, 채널 장애 시 critical 1건이 relay.turn_on 을
최대 10회 재호출(사이렌 ON 연장)했다. 계약: 최초 dispatch 1회 + 재시도 3회 → relay.turn_on 호출 **1회**,
재시도 결과에는 relay·log 채널이 없고 원격 채널 시도 흔적은 남는다(alert_queue._attempted_remote 가 종결 판단에 쓴다).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import agents.dispatcher as _d  # noqa: E402
import alert_queue  # noqa: E402
import relay  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class _Cfg:
    raw = {"dispatch": {"on_severity": {"critical": ["alarm", "manager_call", "safety_relay_signal"]}}}


def _webhook_only_cfg():
    return {"telegram_token": None, "telegram_chat": None, "webhook_url": "http://127.0.0.1:9/hook",
            "smtp_host": None, "smtp_port": 587, "smtp_user": None, "smtp_pass": None, "email_to": None}


class RetryIsRemoteOnly(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.agent = _d.DispatcherAgent(_Cfg())
        self.relay_calls = []
        self._patches = [
            mock.patch.object(_d, "notify_cfg", return_value=_webhook_only_cfg()),
            mock.patch.object(relay, "enabled", return_value=True),
            mock.patch.object(relay, "turn_on",
                              side_effect=lambda msg: (self.relay_calls.append(msg) or
                                                       {"channel": "relay", "sent": True, "action": "on"})),
            # 웹훅은 항상 실패(네트워크 장애 재현)
            mock.patch.object(_d.requests, "post", side_effect=ConnectionError("down")),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_initial_dispatch_then_three_retries_trigger_relay_once(self):
        first = self.agent.dispatch("critical", "지게차 협착")            # 최초: relay 1회 + 원격 실패 → pending
        self.assertFalse(first["delivered"])
        self.assertEqual(len(self.relay_calls), 1)
        row = {"id": 1, "level": "critical", "message": "지게차 협착", "meta": {}, "attempts": 1}
        alert_queue.set_sender(lambda lvl, msg, meta: self.agent._dispatch_now(lvl, msg, meta, remote_only=True))
        for _ in range(3):                                            # 재시도 3회
            alert_queue.try_send(row)
        self.assertEqual(len(self.relay_calls), 1, f"재시도가 relay 를 다시 울렸다: {len(self.relay_calls)}회")

    def test_remote_only_result_has_no_relay_or_log_but_keeps_remote_attempts(self):
        res = self.agent._dispatch_now("critical", "x", {}, remote_only=True)
        channels = [r["channel"] for r in res["results"]]
        self.assertNotIn("relay", channels)
        self.assertNotIn("safety_relay_signal", channels)
        self.assertNotIn("log", channels)
        self.assertIn("webhook", channels)                            # 원격 시도 흔적은 남아야 종결 판단이 된다
        self.assertTrue(alert_queue._attempted_remote(res))
        self.assertFalse(res["delivered"])

    def test_default_dispatch_unchanged(self):
        res = self.agent._dispatch_now("critical", "x", {})
        channels = [r["channel"] for r in res["results"]]
        self.assertIn("relay", channels)
        self.assertIn("log", channels)


if __name__ == "__main__":
    unittest.main()
