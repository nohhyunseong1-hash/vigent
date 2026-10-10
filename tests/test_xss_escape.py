"""tests/test_xss_escape.py — 저장된 XSS(stored XSS) 회귀 (1단계 보안 H-3, 2026-10-10).

배경(점검 실측): 작성자 입력을 그대로 f-string 으로 HTML 에 끼워 넣는 화면이 4곳 있었다 —
TBM 목록(`/safety/tbm`)·TBM 회의록 열람(`/safety/tbm/{tid}`)·감사추적(`/safety/auto/audit`)·
평가서 목록(`/safety/reports`). `POST /safety/tbm`·`POST /safety/auto/approve` 의 본문은
str().strip() 만 거쳐 저장되므로, `<script>` 를 넣어 두면 **그 페이지를 여는 관리자 브라우저에서
실행**됐다(같은 오리진이라 관리자 권한으로 전 API 호출 가능). dashboard.py·demo.py 등 다른
화면들이 이미 쓰는 `html.escape` 를 이 4곳에도 적용한 수정을 회귀 잠금한다.

검증 방식: 악성 문자열을 실제 저장 경로(POST)로 넣고, 렌더링된 HTML 에
① 원문 태그(`<script>`·`<img`)가 그대로 없을 것 ② escape 된 형태(`&lt;script&gt;`)로 남을 것.
저장소는 임시 디렉터리로 격리한다(운영 data/ 불변).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import audit_store  # noqa: E402
import main  # noqa: E402
import tbm_store  # noqa: E402
from agents import scribe as _scribe  # noqa: E402
from app_state import STATE  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

XSS = "<script>alert('xss')</script>"
IMG = '<img src=x onerror=alert(1)>'


class _NoTokenBase(unittest.TestCase):
    """토큰 미설정(로컬 무인증) 상태로 TestClient 를 쓴다 — 기존 test_ws_auth 와 동일 관례."""

    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)

    def tearDown(self):
        if self._prev_token is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token


class TestTbmXssEscape(_NoTokenBase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_tbm_")
        self._saved = (tbm_store._ROOT, tbm_store._TBM)
        tbm_store._ROOT = Path(self._tmp.name)
        tbm_store._TBM = Path(self._tmp.name) / "data" / "tbm"

    def tearDown(self):
        tbm_store._ROOT, tbm_store._TBM = self._saved
        self._tmp.cleanup()
        super().tearDown()

    def _create_poisoned(self) -> str:
        r = self.client.post("/safety/tbm", json={
            "site": XSS, "process": IMG, "work_desc": f"1줄\n{XSS}",
            "supervisor": XSS, "notes": XSS,
            "hazards": [IMG], "checklist": [{"item": XSS, "ok": True}],
            "workers": [{"name": IMG, "signed": False}],
        })
        self.assertEqual(r.status_code, 200)
        return r.json()["id"]

    def test_tbm_list_escapes_stored_fields(self):
        self._create_poisoned()
        body = self.client.get("/safety/tbm").text
        self.assertNotIn(XSS, body)
        self.assertNotIn(IMG, body)
        self.assertIn("&lt;script&gt;", body)

    def test_tbm_open_escapes_stored_fields(self):
        tid = self._create_poisoned()
        body = self.client.get(f"/safety/tbm/{tid}").text
        self.assertNotIn(XSS, body)                  # site·supervisor·notes·checklist(원문 그대로면 실행됨)
        self.assertNotIn(IMG, body)                  # hazards·workers
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img", body)
        # 기능 보존: work_desc 의 줄바꿈 → <br> 변환은 escape 뒤에도 동작해야 한다
        self.assertIn("1줄<br>", body)


class TestAuditXssEscape(_NoTokenBase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_audit_")
        self._saved_dir = audit_store._AUDIT
        audit_store._AUDIT = Path(self._tmp.name) / "data" / "audit"

    def tearDown(self):
        audit_store._AUDIT = self._saved_dir
        self._tmp.cleanup()
        super().tearDown()

    def test_audit_page_escapes_stored_fields(self):
        r = self.client.post("/safety/auto/approve", json={
            "event_ts": "2026-10-10T00:00:00", "action": "acknowledge",
            "approver": XSS, "rule": IMG, "site": XSS,
        })
        self.assertEqual(r.status_code, 200)
        body = self.client.get("/safety/auto/audit").text
        self.assertNotIn(XSS, body)
        self.assertNotIn(IMG, body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("&lt;img", body)

    def test_audit_page_unknown_action_is_escaped(self):
        """act_ko 사전에 없는 action 은 원문 폴백 — 그 폴백도 escape 돼야 한다."""
        self.client.post("/safety/auto/approve", json={
            "event_ts": "t", "action": f"custom{XSS}", "approver": "a", "rule": "r",
        })
        body = self.client.get("/safety/auto/audit").text
        self.assertNotIn(XSS, body)
        self.assertIn("&lt;script&gt;", body)


class TestReportsXssEscape(_NoTokenBase):
    """`/safety/reports` 는 scribe.list_saved()(ra_*.json 의 site 등)를 그대로 표에 끼웠다.
    테마 로드 없이 검증하기 위해 STATE 에 Scribe 로 클래스 자체를 꽂는다(list_saved 는 staticmethod)."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_reports_")
        self._saved_dir = _scribe._SAVE_DIR
        _scribe._SAVE_DIR = Path(self._tmp.name) / "data" / "risk_assessments"
        self._saved_state = STATE.get("safety")
        STATE["safety"] = {"agents": {"Scribe": _scribe.ScribeAgent}}

    def tearDown(self):
        _scribe._SAVE_DIR = self._saved_dir
        if self._saved_state is None:
            STATE.pop("safety", None)
        else:
            STATE["safety"] = self._saved_state
        self._tmp.cleanup()
        super().tearDown()

    def test_reports_list_escapes_stored_fields(self):
        _scribe._SAVE_DIR.mkdir(parents=True, exist_ok=True)
        (_scribe._SAVE_DIR / "ra_20991231_235959.json").write_text(
            '{"generated_at": "<script>g</script>", "site": "<script>s</script>",'
            ' "summary": {"총항목": 1, "상_높음": 0}}', encoding="utf-8")
        body = self.client.get("/safety/reports").text
        self.assertNotIn("<script>g</script>", body)
        self.assertNotIn("<script>s</script>", body)
        self.assertIn("&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()
