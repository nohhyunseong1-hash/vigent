"""CODE_AUDIT_20260928 #7 — notify.example.yaml 이 실제 스키마이고, notify.yaml 파싱 실패는 숨지 않는다. [2026-09-28]

★무엇을 고정하는가
  ① 예시 파일을 그대로 notify.yaml 로 복사해 토큰·chat 만 채우면 dispatcher.notify_cfg() 가 그 값을 읽는다(평면 키).
  ② YAML 문법 오류면 ERROR 1회 + selftest state=config_error(reason 에 "notify.yaml 파싱 실패"), 고치면 해제된다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import agents.dispatcher as D  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
FAKE_TOKEN = "123456789:AAEexampleTOKENexampleTOKENexample"


class ExampleMatchesSchema(unittest.TestCase):
    def setUp(self):
        D.reset_delivery_stats_for_test(); self.addCleanup(D.reset_delivery_stats_for_test)
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name); (self.root / "config").mkdir()
        p = mock.patch.object(D, "_ROOT", self.root); p.start(); self.addCleanup(p.stop)
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO"):
            self.addCleanup(mock.patch.dict("os.environ", {}, clear=False).stop) if False else None
        self.env = mock.patch.dict("os.environ", {k: "" for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO")})
        self.env.start(); self.addCleanup(self.env.stop)

    def _write(self, text: str):
        (self.root / "config" / "notify.yaml").write_text(text, encoding="utf-8")

    def test_example_copied_and_filled_is_read(self):
        ex = (_ROOT / "config" / "notify.example.yaml").read_text(encoding="utf-8")
        filled = ex.replace('telegram_token: ""', f'telegram_token: "{FAKE_TOKEN}"').replace('telegram_chat: ""', 'telegram_chat: "-1001234"')
        self._write(filled)
        c = D.notify_cfg()
        self.assertEqual(c["telegram_token"], FAKE_TOKEN); self.assertEqual(c["telegram_chat"], "-1001234"); self.assertEqual(c["smtp_port"], 587)
        self.assertIsNone(c["webhook_url"]); self.assertIsNone(c["email_to"])
        for key in ("telegram_token", "telegram_chat", "webhook_url", "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "email_to"):
            self.assertIn(f"{key}:", ex, f"예시에 {key} 키가 없다")
        parsed = yaml.safe_load(ex) or {}
        self.assertNotIn("telegram", parsed, "중첩 telegram: 블록(구 스키마)이 있으면 안 된다"); self.assertNotIn("bot_token", parsed)

    def test_parse_error_is_logged_once_and_flagged(self):
        self._write("telegram_token: [unclosed\n  smtp_port: 587\n")
        with self.assertLogs("vigent.dispatcher", level="ERROR") as cm:
            c1 = D.notify_cfg(); c2 = D.notify_cfg()
        self.assertIsNone(c1["telegram_token"]); self.assertIsNone(c2["telegram_token"])
        self.assertEqual(sum(1 for m in cm.output if "파싱 실패" in m), 1, "같은 오류는 1회만")
        st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "config_error"); self.assertIn("notify.yaml 파싱 실패", st["reason"])
        # 고치면 해제
        self._write(f'telegram_token: "{FAKE_TOKEN}"\ntelegram_chat: "1"\n')
        c3 = D.notify_cfg()
        self.assertEqual(c3["telegram_token"], FAKE_TOKEN); self.assertIsNone(D._PARSE_ERROR["sig"]); self.assertNotEqual(D._SELFTEST["state"], "config_error")

    def test_non_mapping_top_level_is_a_parse_error(self):
        self._write("- just\n- a list\n")
        with self.assertLogs("vigent.dispatcher", level="ERROR"):
            c = D.notify_cfg()
        self.assertIsNone(c["telegram_token"]); self.assertIsNotNone(D._PARSE_ERROR["sig"])


if __name__ == "__main__":
    unittest.main()
