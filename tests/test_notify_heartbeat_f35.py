"""[F-35] 하루 1회 heartbeat — 침묵이 신호가 되게 한다.

★왜 필요한가: 배너·CRITICAL 은 사람이 화면·로그를 볼 때만 보인다.
  2026-08-21~09-10 에 401 로 20일간 경보가 못 갔는데 **아무 신호도 없었다.**
  하루 한 번 오는 메시지가 **안 오면** 사람이 알아차린다.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))


class HeartbeatTest(unittest.TestCase):
    def setUp(self) -> None:
        import notify_heartbeat as H
        self.H = H
        H.reset_for_test()
        self.sent: list[str] = []
        self._orig = H.configured_at

    def tearDown(self) -> None:
        self.H.configured_at = self._orig
        self.H.reset_for_test()

    def _sender(self, text: str) -> dict[str, Any]:
        self.sent.append(text)
        return {"channel": "telegram", "sent": True}

    def test_disabled_when_not_configured(self) -> None:
        """★미설정이면 **끈다** — 기본 동작을 바꾸지 않는다."""
        self.H.configured_at = lambda: None
        r = self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=self._sender)
        self.assertFalse(r["sent"])
        self.assertEqual(self.sent, [])

    def test_not_sent_before_time(self) -> None:
        self.H.configured_at = lambda: "09:00"
        r = self.H.maybe_send(dt.datetime(2026, 9, 22, 8, 59), sender=self._sender)
        self.assertFalse(r["sent"])
        self.assertEqual(self.sent, [])

    def test_sends_once_at_time(self) -> None:
        """★지정 시각 도달 시 **1회만** — 30초마다 깨어나도 중복 발송하지 않는다."""
        self.H.configured_at = lambda: "09:00"
        r1 = self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=self._sender)
        self.assertTrue(r1["sent"])
        self.assertEqual(len(self.sent), 1)
        for minute in (1, 5, 30):                       # 같은 날 반복 호출
            self.H.maybe_send(dt.datetime(2026, 9, 22, 9, minute), sender=self._sender)
        self.assertEqual(len(self.sent), 1, "하루 1회만 보내야 한다")

    def test_sends_again_next_day(self) -> None:
        self.H.configured_at = lambda: "09:00"
        self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=self._sender)
        self.H.maybe_send(dt.datetime(2026, 9, 23, 9, 0), sender=self._sender)
        self.assertEqual(len(self.sent), 2)

    def test_message_format(self) -> None:
        self.H.configured_at = lambda: "09:00"
        self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=self._sender)
        self.assertRegex(self.sent[0], r"^VIGENT 알림 채널 정상 · 오늘 경보 \d+건 · 데드레터 \d+건$")

    def test_send_failure_does_not_retry_same_day(self) -> None:
        """전송이 실패해도 하루 1회만 시도한다(폭주 방지). 실패는 로그로 남는다."""
        self.H.configured_at = lambda: "09:00"
        def _fail(_t: str) -> dict[str, Any]:
            self.sent.append("시도")
            return {"sent": False, "reason": "401"}
        with self.assertLogs("vigent.heartbeat", level="WARNING"):
            self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=_fail)
        self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 10), sender=_fail)
        self.assertEqual(len(self.sent), 1)

    def test_health_shows_heartbeat_failure(self) -> None:
        """★heartbeat 전송 실패가 /health 에 드러나야 한다.

        heartbeat 가 조용히 실패하면 '침묵이 신호' 라는 설계 자체가 무너진다 —
        메시지가 안 온 게 채널 문제인지 heartbeat 문제인지 사람이 가릴 수 있어야 한다.
        """
        self.H.configured_at = lambda: "09:00"
        def _fail(_t: str) -> dict[str, Any]:
            return {"sent": False, "reason": "401"}
        with self.assertLogs("vigent.heartbeat", level="WARNING"):
            self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=_fail)
        st = self.H.status()
        self.assertIsNotNone(st["last_sent_ts"], "시도 시각이 남아야 한다")
        self.assertFalse(st["last_ok"], "실패가 false 로 드러나야 한다")
        # 성공했을 때는 true
        self.H.reset_for_test()
        self.H.configured_at = lambda: "09:00"
        self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=self._sender)
        st2 = self.H.status()
        self.assertTrue(st2["last_ok"])
        self.assertIsNotNone(st2["last_sent_ts"])

    def test_bad_time_format_is_off(self) -> None:
        """형식이 틀리면 조용히 켜지 않는다 — 잘못된 설정으로 엉뚱한 시각에 보내지 않는다."""
        import tuning
        orig = tuning.val
        tuning.val = lambda *a, **k: "9시"      # 잘못된 형식
        try:
            with self.assertLogs("vigent.heartbeat", level="WARNING"):
                self.assertIsNone(self.H.configured_at())
        finally:
            tuning.val = orig


if __name__ == "__main__":
    unittest.main()
