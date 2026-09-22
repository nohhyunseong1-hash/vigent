"""[CODE_REVIEW M4-1·M4-2·M4-3·M4-7] 통보 전달 견고화 — 채널 미설정·설정 오류·데드레터·본문 길이.

M4-1 채널 미설정: 원격 채널이 하나도 없으면 critical/high 를 큐에 넣지 않고(재시도 무의미) undeliverable 로 센다.
      /health 는 미설정 자체를 warnings["channels_not_configured"] 로만 알리고(status ok), critical/high 가 발생해
      폐기된 경우에만 degraded(alerts.undeliverable).
M4-3 HTTP 코드 분류: 400/401/403/404 = config_error → 즉시 dead + dispatcher.status().last_config_error(토큰 제외).
      429 = 재시도(Retry-After 존중, 없으면 기존 백오프). 5xx·타임아웃·네트워크 = 기존 재시도.
M4-2 데드레터 발생 → 살아 있는 채널로 요약 통보 1회/시간(게이트 키 system/alert_dead). 자기 자신(alert_dead)은 재귀 금지.
M4-7 텔레그램 본문 4096자 제한 → 4000자 절단.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import agents.dispatcher as _d  # noqa: E402
import alert_queue as q  # noqa: E402
import health_status  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class _Cfg:
    raw = {"dispatch": {"on_severity": {"critical": ["alarm", "manager_call", "safety_relay_signal"],
                                        "high": ["alarm", "manager_call"], "medium": ["log"]}}}


def _cfg(**over):
    base = {"telegram_token": None, "telegram_chat": None, "webhook_url": None,
            "smtp_host": None, "smtp_port": 587, "smtp_user": None, "smtp_pass": None, "email_to": None}
    base.update(over)
    return base


def _tg(**over):
    return _cfg(telegram_token="000000:SECRET-TOKEN-VALUE-abcdefghijklmnop", telegram_chat="12345", **over)


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}


class ChannelsNotConfigured(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.agent = _d.DispatcherAgent(_Cfg())
        _d.reset_delivery_stats_for_test()

    def test_no_channels_means_no_queue_but_counted(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_cfg()):
            self.assertFalse(self.agent.channels_configured())
            self.assertFalse(self.agent._queue_enabled("critical"))
            r = self.agent.dispatch("critical", "지게차 협착")
            st = self.agent.status()                  # status() 도 notify_cfg 를 읽으므로 모킹 안에서
        self.assertFalse(r["delivered"])
        self.assertEqual(q.counts()["pending"], 0, "채널이 없는데 큐에 넣었다(재시도 무의미)")
        self.assertFalse(st["channels_configured"])
        self.assertEqual(st["undeliverable_count"], 1)

    def test_log_only_level_is_not_undeliverable(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_cfg()):
            self.agent.dispatch("medium", "기록 전용")
        self.assertEqual(self.agent.status()["undeliverable_count"], 0)

    def test_health_warning_vs_degraded(self):
        """미설정 자체 = 경고만(ok). critical/high 폐기가 있었을 때만 degraded."""
        problems, warnings = health_status.alert_health({"pending": 0, "dead": 0, "dead_1h": 0},
                                                        {"channels_configured": False, "undeliverable_count": 0})
        self.assertEqual(problems, 0)
        self.assertIn("channels_not_configured", warnings)
        problems, _ = health_status.alert_health({"pending": 0, "dead": 0, "dead_1h": 0},
                                                 {"channels_configured": False, "undeliverable_count": 2})
        self.assertGreater(problems, 0)
        self.assertEqual(health_status.overall({}, True, alert_backlog=0, alert_problems=problems),
                         health_status.DEGRADED)


class HttpCodeClassification(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.agent = _d.DispatcherAgent(_Cfg())
        _d.reset_delivery_stats_for_test()
        q.set_sender(lambda lvl, msg, meta: self.agent._dispatch_now(lvl, msg, meta, remote_only=True))

    def _row(self, level="high"):
        rid = q.enqueue(level, "m")
        return {"id": rid, "level": level, "message": "m", "meta": {}, "attempts": 0}

    def _status(self, rid):
        return q._db().execute("SELECT status, attempts, last_error, next_attempt_at FROM alerts WHERE id=?",
                               (rid,)).fetchone()

    def test_401_is_config_error_dead_immediately(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_tg()), \
                mock.patch.object(_d.requests, "post", return_value=_Resp(401)):
            row = self._row()
            q.try_send(row)
        st, attempts, err, _ = self._status(row["id"])
        self.assertEqual(st, "dead", "설정 오류(401)는 재시도해도 영원히 실패 — 즉시 dead 여야 한다")
        self.assertEqual(attempts, 1)
        self.assertIn("config_error", err)
        # ★[F-35, 2026-09-22] 형식이 dict → **문자열**로 통일됐다.
        #   예전엔 _dispatch_now 는 dict 를, 자가시험 경로는 문자열을 넣어 /health 의
        #   notify.config_error 모양이 경로에 따라 달라졌다. 이제 둘 다 "채널 HTTP 코드".
        lce = self.agent.status()["last_config_error"]
        self.assertEqual(lce, "telegram HTTP 401")
        self.assertNotIn("SECRET-TOKEN", str(self.agent.status()), "status 에 토큰이 새면 안 된다")

    def test_429_retries_with_retry_after(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_tg()), \
                mock.patch.object(_d.requests, "post", return_value=_Resp(429, {"Retry-After": "7"})):
            row = self._row()
            t0 = time.time()
            q.try_send(row)
        st, attempts, _err, nxt = self._status(row["id"])
        self.assertEqual(st, "pending")
        self.assertEqual(attempts, 1)
        self.assertTrue(6.0 <= nxt - t0 <= 8.5, f"Retry-After 7s 를 존중해야 한다: {nxt - t0:.1f}s")

    def test_5xx_uses_default_backoff(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_tg()), \
                mock.patch.object(_d.requests, "post", return_value=_Resp(503)):
            row = self._row()
            t0 = time.time()
            q.try_send(row)
        st, attempts, _err, nxt = self._status(row["id"])
        self.assertEqual(st, "pending")
        self.assertTrue(0.0 <= nxt - t0 <= 2.0, "5xx 는 기존 지수 백오프(1회째 1s)")   # 2**0 = 1s

    def test_network_error_uses_default_backoff(self):
        with mock.patch.object(_d, "notify_cfg", return_value=_tg()), \
                mock.patch.object(_d.requests, "post", side_effect=ConnectionError("down")):
            row = self._row()
            q.try_send(row)
        self.assertEqual(self._status(row["id"])[0], "pending")


class DeadLetterNotify(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        q._reset_dead_notify_for_test()

    def test_dead_notifies_once_per_hour_and_not_recursive(self):
        with mock.patch.object(q, "_submit_dead_summary") as sub:
            r1 = q.enqueue("high", "a"); r2 = q.enqueue("high", "b")
            for rid in (r1, r2):
                for _ in range(q.max_attempts()):
                    q.mark_failed(rid, "boom")
            self.assertEqual(q.counts()["dead"], 2)
            self.assertEqual(sub.call_count, 1, "데드레터 요약 통보는 1시간에 1회")
            r3 = q.enqueue("high", "데드레터 요약", {"rule": "alert_dead"})
            q.mark_dead(r3, "config_error: 401")
            self.assertEqual(sub.call_count, 1, "요약 통보 자신이 죽어도 재귀 통보하지 않는다")

    def test_counts_include_dead_1h(self):
        rid = q.enqueue("high", "x")
        q.mark_dead(rid, "config_error: 403")
        c = q.counts()
        self.assertEqual(c["dead"], 1)
        self.assertEqual(c["dead_1h"], 1)


class TelegramTruncation(unittest.TestCase):
    def test_long_text_is_cut_to_4000(self):
        agent = _d.DispatcherAgent(_Cfg())
        sent = {}

        def _post(url, json=None, timeout=None):
            sent.update(json or {})
            return _Resp(200)
        with mock.patch.object(_d, "notify_cfg", return_value=_tg()), \
                mock.patch.object(_d.requests, "post", side_effect=_post):
            r = agent._send_telegram("가" * 5000)
        self.assertTrue(r["sent"])
        self.assertLessEqual(len(sent["text"]), 4000)


if __name__ == "__main__":
    unittest.main()
