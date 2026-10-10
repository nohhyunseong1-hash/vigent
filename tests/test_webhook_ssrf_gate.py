"""tests/test_webhook_ssrf_gate.py — 웹훅 SSRF 차단 회귀 (1단계 보안 H-4, 2026-10-10).

배경(점검 실측): 화이트리스트 장치 `web_util.webhook_allowed`(config/security.json
allowed_webhook_hosts, fail-closed)가 **만들어져 있었는데** 호출부가 routers/dispatch.py 의
수동 시험 경로 하나뿐이었다 — 정작 실제 전송 경로(`dispatcher._send_webhook`)와 저장 경로
(`POST /notify/config` → setup_console.write_notify)는 검사 없이 임의 URL 을 받았다.
→ ① 공격자가 webhook_url 을 내부망 주소로 저장하면 서버가 대신 POST(SSRF, /alerts/test 로
즉시 발사 가능) ② 이후의 모든 실제 경보가 그 주소로 유출. 두 경로 모두에 화이트리스트를
배선한 수정을 회귀 잠금한다.

검증: 미허용 호스트는 ① 저장이 400 으로 거부되고 yaml 이 바뀌지 않으며 ② 전송 경로는
requests.post 를 **호출조차 하지 않고** config_error 로 반환. 허용 호스트(hooks.slack.com)는
저장·전송 모두 기존대로 동작(안전경보 경로를 정상설정에서 막지 않음).
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
import setup_console  # noqa: E402
from agents import dispatcher as _dispatcher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

EVIL = "http://169.254.169.254/latest/meta-data"      # 내부망(클라우드 메타데이터) 꼴
GOOD = "https://hooks.slack.com/services/T000/B000/x"  # security.json 허용 목록에 있는 호스트


def _make_dispatcher() -> "_dispatcher.DispatcherAgent":
    cfg = types.SimpleNamespace(raw={})
    return _dispatcher.DispatcherAgent(cfg)


class _FakeResponse:
    ok = True
    status_code = 200
    headers: dict = {}


class TestSendWebhookGate(unittest.TestCase):
    """전송 직전 차단 — notify_cfg 를 바꿔치기해 임의 webhook_url 상태를 재현한다."""

    def setUp(self):
        self._saved_cfg = _dispatcher.notify_cfg
        self._saved_requests = _dispatcher.requests
        self.calls = []

    def tearDown(self):
        _dispatcher.notify_cfg = self._saved_cfg
        _dispatcher.requests = self._saved_requests

    def _patch(self, url: str):
        _dispatcher.notify_cfg = lambda: {"webhook_url": url}
        fake = types.SimpleNamespace(post=lambda *a, **kw: (self.calls.append((a, kw)), _FakeResponse())[1])
        _dispatcher.requests = fake

    def test_disallowed_host_is_blocked_without_network(self):
        self._patch(EVIL)
        out = _make_dispatcher()._send_webhook({"m": 1})
        self.assertFalse(out["sent"])
        self.assertTrue(out.get("config_error"))
        self.assertIn("미허용", out.get("reason", ""))
        self.assertEqual(self.calls, [])     # requests.post 호출 자체가 없어야 한다

    def test_allowed_host_still_sends(self):
        self._patch(GOOD)
        out = _make_dispatcher()._send_webhook({"m": 1})
        self.assertTrue(out["sent"])
        self.assertEqual(len(self.calls), 1)


class TestWriteNotifyGate(unittest.TestCase):
    """저장 시점 차단 — notify.yaml 을 임시 파일로 격리하고 /notify/config 로 실제 요청."""

    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_notify_")
        self._saved_notify = setup_console._NOTIFY
        setup_console._NOTIFY = Path(self._tmp.name) / "notify.yaml"

    def tearDown(self):
        setup_console._NOTIFY = self._saved_notify
        self._tmp.cleanup()
        if self._prev_token is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token

    def test_disallowed_host_rejected_with_400_and_not_saved(self):
        r = self.client.post("/notify/config", json={"webhook_url": EVIL})
        self.assertEqual(r.status_code, 400)
        self.assertIn("미허용", r.json().get("detail", ""))
        # 파일이 아예 안 만들어졌거나, 만들어졌어도 그 주소가 없어야 한다
        p = setup_console._NOTIFY
        saved = p.read_text(encoding="utf-8") if p.exists() else ""
        self.assertNotIn("169.254.169.254", saved)

    def test_allowed_host_saved_ok(self):
        r = self.client.post("/notify/config", json={"webhook_url": GOOD})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))
        self.assertIn("hooks.slack.com", setup_console._NOTIFY.read_text(encoding="utf-8"))

    def test_empty_webhook_still_ok(self):
        """webhook 미사용(빈 값) 저장은 기존대로 통과 — 텔레그램만 쓰는 현장 설정을 막지 않는다."""
        r = self.client.post("/notify/config", json={"webhook_url": "", "telegram_chat": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))


if __name__ == "__main__":
    unittest.main()
