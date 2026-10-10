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

    def test_send_failure_retries_after_interval(self) -> None:
        """[2단계 A-1] 실패는 날짜 도장을 찍지 않는다 — 재시도 간격(기본 600초) 안에서는
        대기(폭주 방지), 간격이 지나면 재시도, 성공해야 그날이 끝난다.
        예전엔 실패에도 도장을 찍어 '그날은 포기' 였다 — 채널이 하루 중 잠깐만 죽어도
        heartbeat 가 안 가는 날이 생겼다."""
        self.H.configured_at = lambda: "09:00"
        attempts: list[str] = []
        def _fail(_t: str) -> dict[str, Any]:
            attempts.append("시도")
            return {"sent": False, "reason": "401"}
        with self.assertLogs("vigent.heartbeat", level="WARNING"):
            self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 0), sender=_fail)
        self.assertIsNone(self.H.status()["last_sent_date"], "실패에는 날짜 도장이 없어야 한다")
        # 간격(600초) 안 — 재시도하지 않고 대기(30초 폭주 방지)
        r = self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 5), sender=_fail)
        self.assertFalse(r["sent"])
        self.assertIn("재시도 대기", r["reason"])
        self.assertEqual(len(attempts), 1)
        # 간격이 지나면 재시도 — 이번엔 성공 → 그날 도장
        r2 = self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 15), sender=self._sender)
        self.assertTrue(r2["sent"])
        self.assertEqual(self.H.status()["last_sent_date"], "2026-09-22")
        # 성공 후 같은 날 재발송 없음(기존 하루 1회 보장 유지)
        self.H.maybe_send(dt.datetime(2026, 9, 22, 9, 30), sender=self._sender)
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

    def test_sends_to_all_configured_channels(self) -> None:
        """★heartbeat 는 설정된 **원격 채널 전부**로 간다 — 이메일이 죽어도 알아야 한다.

        텔레그램만 보내면, 정작 텔레그램이 죽었을 때 쓰려고 만든 두 번째 채널의
        상태를 확인할 길이 없어진다.
        """
        import app_state
        H = self.H
        calls: list[str] = []

        class _Agent:
            @staticmethod
            def _send_telegram(text: str) -> dict[str, Any]:
                calls.append("telegram")
                return {"channel": "telegram", "sent": True}

            @staticmethod
            def _send_email(subject: str, text: str) -> dict[str, Any]:
                calls.append("email")
                return {"channel": "email", "sent": False, "status": 535, "config_error": True}

        from agents import dispatcher as D
        orig_cfg = D.notify_cfg
        D.notify_cfg = lambda: {"telegram_token": "t", "telegram_chat": "c", "webhook_url": None,
                                "smtp_host": "smtp.x", "smtp_user": "u", "smtp_pass": "p",
                                "email_to": "to@x", "smtp_port": 587}
        # [2단계 A-1] STATE 는 **테마명으로 키**된다 — 예전 이 테스트는 존재하지 않는
        # "bundle" 키를 꽂아 코드의 같은 오가정을 가려 줬다(실제로는 한 번도 발송 안 됨).
        theme = app_state.DEFAULT_THEME
        prev_bundle = app_state.STATE.get(theme)
        app_state.STATE[theme] = {"agents": {"Dispatcher": _Agent}}
        try:
            res = H._send_all_channels("점검")
        finally:
            D.notify_cfg = orig_cfg
            if prev_bundle is None:
                app_state.STATE.pop(theme, None)
            else:
                app_state.STATE[theme] = prev_bundle
        self.assertEqual(sorted(calls), ["email", "telegram"], "두 채널 모두 시도해야 한다")
        self.assertTrue(res["sent"], "하나라도 성공하면 sent(경보와 같은 규칙)")
        self.assertEqual(res["sent_channels"], ["telegram"])
        self.assertEqual(res["failed_channels"], ["email:535"])

    def test_real_send_path_via_maybe_send(self) -> None:
        """[2단계 A-1 회귀 잠금] sender 인자 없이(= 운영과 동일 경로) maybe_send 가
        STATE 의 테마 번들에서 Dispatcher 를 찾아 **실제로 채널 함수를 호출**하는지.
        예전 코드는 STATE["bundle"] 을 읽어 agent 가 항상 None → 영구 미발송이었다."""
        import app_state
        H = self.H
        calls: list[str] = []

        class _Agent:
            @staticmethod
            def _send_telegram(text: str) -> dict[str, Any]:
                calls.append(text)
                return {"channel": "telegram", "sent": True}

        from agents import dispatcher as D
        orig_cfg = D.notify_cfg
        D.notify_cfg = lambda: {"telegram_token": "t", "telegram_chat": "c", "webhook_url": None,
                                "smtp_host": "", "smtp_user": "", "smtp_pass": "", "email_to": ""}
        theme = app_state.DEFAULT_THEME
        prev_bundle = app_state.STATE.get(theme)
        app_state.STATE[theme] = {"agents": {"Dispatcher": _Agent}}
        H.configured_at = lambda: "09:00"
        try:
            r = H.maybe_send(dt.datetime(2026, 9, 22, 9, 0))      # sender 미지정 = 실제 경로
        finally:
            D.notify_cfg = orig_cfg
            if prev_bundle is None:
                app_state.STATE.pop(theme, None)
            else:
                app_state.STATE[theme] = prev_bundle
        self.assertTrue(r["sent"], f"실제 경로로 발송돼야 한다: {r}")
        self.assertEqual(len(calls), 1)
        self.assertIn("VIGENT 알림 채널 정상", calls[0])

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
