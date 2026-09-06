"""[CODE_REVIEW M8-8·M6-3] 자동처리 콘솔 2화면의 📌 보존/해제 버튼 — 피드가 증거 상대경로·pin 상태를 실어 주고 버튼이 /recognition/pin|unpin 을 부른다."""
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import data_engine  # noqa: E402
import main  # noqa: E402
from _isolate import isolate_data_dirs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from routers import safety_core  # noqa: E402

_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class ConsolePinFeed(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_data_dirs())
        self._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        self.addCleanup(setattr, main, "_API_TOKEN", self._saved_token)
        p = mock.patch.dict(safety_core.STATE, {safety_core.DEFAULT_THEME: {"agents": {}}})
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(main.app)

    def test_feed_carries_evidence_path_and_pin_state_roundtrip(self):
        rec = data_engine.log_event(rule="zone_intrusion", level="high", site="t", note="n", image_data_url=_PNG)
        self.assertTrue(rec["evidence"])
        f = self.client.get("/safety/auto/feed").json()
        ev = f["events"][0]
        self.assertEqual(ev["evidence"], rec["evidence"].replace("\\", "/"))
        self.assertFalse(ev["pinned"])
        self.assertEqual(self.client.post("/recognition/pin", json={"path": ev["evidence"]}).status_code, 200)
        self.assertTrue(self.client.get("/safety/auto/feed").json()["events"][0]["pinned"])
        self.assertEqual(self.client.post("/recognition/unpin", json={"path": ev["evidence"]}).status_code, 200)
        self.assertFalse(self.client.get("/safety/auto/feed").json()["events"][0]["pinned"])

    def test_console_pages_have_pin_buttons(self):
        auto = (_ROOT / "vigent-core" / "templates" / "auto.html").read_text(encoding="utf-8")
        term = (_ROOT / "vigent-core" / "static" / "auto_terminal.html").read_text(encoding="utf-8")
        for name, t in (("auto.html", auto), ("auto_terminal.html", term)):
            self.assertIn("'/recognition/'+", t, name)           # fetch('/recognition/'+action) — pin | unpin
            self.assertIn("'unpin'", t, name)
            self.assertIn("'pin'", t, name)
            self.assertIn("📌", t, name)


if __name__ == "__main__":
    unittest.main()
