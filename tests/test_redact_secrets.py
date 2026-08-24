"""[2026-08-21] 통보 채널 오류 메시지에서 비밀값이 새지 않는지.

배경(현장 노트북 실측): 텔레그램 전송 실패 시 requests 예외 메시지가 URL 을 통째로 담고,
텔레그램은 **URL 경로에 봇 토큰**을 넣는다. 그 문자열이 그대로
`logs/vigent.err.log`·경보 DB(`last_error`)·API 응답으로 흘러 평문 토큰이 퍼졌다:

    [ERROR] vigent.alert_queue: 경보 데드레터(...) [{'channel': 'telegram', ...
      'reason': "...Max retries exceeded with url: /bot<진짜토큰>/sendMessage"}]

카메라 자격증명을 data/camera_secrets.json 에만 두고 로그엔 마스킹하는 기존 원칙과
어긋나 있었다. 진단 가능성은 유지해야 하므로 **호스트·채널은 남기고 비밀값만** 지운다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

from agents.dispatcher import redact_secrets  # noqa: E402

REAL_LOOKING = "8205368768:AAEMC_5Tz6tMbD09BKLcYOA7Rym6MabcdefghIJ"


class TestRedactSecrets(unittest.TestCase):

    def test_telegram_token_in_url_is_removed(self):
        msg = (f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
               f"Max retries exceeded with url: /bot{REAL_LOOKING}/sendMessage")
        out = redact_secrets(msg)
        self.assertNotIn(REAL_LOOKING, out)
        self.assertNotIn("AAEMC", out)
        self.assertIn("bot<REDACTED>", out)
        # 진단에 필요한 정보는 남아야 한다
        self.assertIn("api.telegram.org", out)
        self.assertIn("sendMessage", out)

    def test_slack_webhook_path_is_removed(self):
        msg = "POST https://hooks.slack.com/services/T0AAA/B0BBB/xoxbSECRETVALUE failed"
        out = redact_secrets(msg)
        self.assertNotIn("xoxbSECRETVALUE", out)
        self.assertNotIn("T0AAA", out)
        self.assertIn("hooks.slack.com/services/<REDACTED>", out)

    def test_discord_webhook_path_is_removed(self):
        out = redact_secrets("https://discord.com/api/webhooks/123456/SECRETPART")
        self.assertNotIn("SECRETPART", out)
        self.assertIn("<REDACTED>", out)

    def test_querystring_secrets_are_removed(self):
        for key in ("token", "key", "api_key", "access_token", "TOKEN"):
            with self.subTest(key=key):
                out = redact_secrets(f"GET https://x.example/api?{key}=SUPERSECRET&z=1 failed")
                self.assertNotIn("SUPERSECRET", out)
                self.assertIn("z=1", out)          # 뒤 파라미터는 보존

    def test_ordinary_message_unchanged(self):
        for msg in ("연결 시간 초과 — api.telegram.org 도달 불가",
                    "SMTP 미설정",
                    "requests 미설치"):
            self.assertEqual(redact_secrets(msg), msg)

    def test_multiple_secrets_in_one_message(self):
        msg = (f"bot{REAL_LOOKING}/sendMessage and "
               "https://hooks.slack.com/services/A/B/CSECRET")
        out = redact_secrets(msg)
        self.assertNotIn(REAL_LOOKING, out)
        self.assertNotIn("CSECRET", out)


if __name__ == "__main__":
    unittest.main()
