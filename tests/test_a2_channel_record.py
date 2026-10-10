"""tests/test_a2_channel_record.py — 1차 전송 경로의 채널별 기록 회귀 (2단계 A-2, 2026-10-10).

배경(점검 실측, OPEN_ISSUES #14): 재시도 경로(alert_queue.try_send)는 mark_sent 에
채널 목록(sent_ch/failed_ch)을 넘기는데, **1차 전송 경로**(dispatcher.dispatch)만 인자
없이 불러 channels_sent 가 NULL 로 남았다 → counts()["email_last_success"] 가 영구
None → "텔레그램은 가는데 이메일만 죽은" 상태를 /health 가 영원히 못 잡았다
(F-35 침묵 사고가 막으려던 바로 그 고장 모드).

검증: 텔레그램 성공·이메일 실패를 흉내낸 dispatch 1회 뒤 — 행의 channels_sent 에
"telegram", channels_failed 에 "email:" 이 남고, 이메일까지 성공한 경우
counts()["email_last_success"] 가 시각으로 채워지는지.
"""
import json
import sqlite3
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))
sys.path.insert(0, str(ROOT / "tests"))

from _isolate import isolate_alerts  # noqa: E402


def _make_agent():
    from agents import dispatcher as D
    return D.DispatcherAgent(types.SimpleNamespace(raw={}))


class TestChannelRecordOnFirstSend(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        from agents import dispatcher as D
        self.D = D
        self._orig_cfg = D.notify_cfg
        D.notify_cfg = lambda: {"telegram_token": "t", "telegram_chat": "c", "webhook_url": "",
                                "smtp_host": "smtp.x", "smtp_user": "u", "smtp_pass": "p",
                                "email_to": "to@x", "smtp_port": 587}

    def tearDown(self):
        self.D.notify_cfg = self._orig_cfg

    def _row(self):
        import alert_queue
        con = sqlite3.connect(str(alert_queue._DB_PATH))
        try:
            return con.execute(
                "SELECT status, channels_sent, channels_failed FROM alerts LIMIT 1").fetchone()
        finally:
            con.close()

    def test_first_send_records_channels(self):
        agent = _make_agent()
        agent._send_telegram = lambda text: {"channel": "telegram", "sent": True}
        agent._send_email = lambda subject, text: {"channel": "email", "sent": False, "status": 535}
        agent._send_webhook = lambda payload: {"channel": "webhook", "sent": False, "reason": "미설정"}
        res = agent.dispatch("high", "채널기록 테스트")
        self.assertTrue(res["delivered"])
        row = self._row()
        self.assertIsNotNone(row, "선기록 행이 있어야 한다")
        self.assertEqual(row[0], "sent")
        self.assertIn("telegram", json.loads(row[1] or "[]"))
        self.assertTrue(any(f.startswith("email:") for f in json.loads(row[2] or "[]")),
                        f"이메일 실패가 channels_failed 에 남아야 한다: {row[2]}")

    def test_email_last_success_now_visible(self):
        """이메일까지 성공하면 counts()['email_last_success'] 가 시각으로 채워진다 —
        예전엔 1차 경로가 채널을 안 남겨 영구 None 이었다."""
        import alert_queue
        agent = _make_agent()
        agent._send_telegram = lambda text: {"channel": "telegram", "sent": True}
        agent._send_email = lambda subject, text: {"channel": "email", "sent": True}
        agent._send_webhook = lambda payload: {"channel": "webhook", "sent": False, "reason": "미설정"}
        agent.dispatch("high", "이메일 성공 기록 테스트")
        self.assertIsNotNone(alert_queue.counts().get("email_last_success"),
                             "1차 전송 성공만으로 email_last_success 가 보여야 한다")


if __name__ == "__main__":
    unittest.main()
