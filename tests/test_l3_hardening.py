"""tests/test_l3_hardening.py — 1단계 L-3 소규모 보강 묶음 회귀 (2026-10-10).

① 비ASCII Authorization 헤더 → 예전엔 hmac.compare_digest TypeError 로 **500**(시끄러운
   오라클) — 이제 깔끔한 401(HTTP)·인증 실패(로그인 폼·WS) 로 처리(fail-closed).
② 세션 저장소 무한 증가 — validate 로 읽힌 세션만 지워서 반복 로그인 환경에서
   auth_session._sessions 가 계속 자랐다 → create_session 때 만료분 일괄 청소.
③ WS 쿼리 `?token=` 폐지는 test_ws_auth.py 에서 잠금(URL 로그·히스토리에 토큰 잔존).
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import auth_session  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestNonAsciiAuthHeader(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev = (main._API_TOKEN, main._ALLOWED_HOSTS)
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None

    def tearDown(self):
        main._API_TOKEN, main._ALLOWED_HOSTS = self._prev

    def test_non_ascii_bearer_is_401_not_500(self):
        """Starlette 는 헤더를 latin-1 로 디코드한다 — 127 초과 바이트(é)를 담아 보내면
        compare_digest 가 비ASCII str 에 TypeError 를 던지던 경로를 그대로 재현한다."""
        r = self.client.get("/status",
                            headers={b"Authorization": "Bearer tok\xe9n".encode("latin-1")})
        self.assertEqual(r.status_code, 401)

    def test_check_token_non_ascii_false_not_raise(self):
        self.assertFalse(auth_session.check_token("한글오타", "secret-xyz"))


class TestSessionSweep(unittest.TestCase):
    def setUp(self):
        self._saved = dict(auth_session._sessions)
        auth_session._sessions.clear()

    def tearDown(self):
        auth_session._sessions.clear()
        auth_session._sessions.update(self._saved)

    def test_expired_sessions_removed_on_create(self):
        auth_session._sessions["expired-1"] = time.time() - 10
        auth_session._sessions["expired-2"] = time.time() - 99
        live = auth_session.create_session()
        self.assertNotIn("expired-1", auth_session._sessions)
        self.assertNotIn("expired-2", auth_session._sessions)
        self.assertIn(live, auth_session._sessions)

    def test_live_sessions_kept(self):
        auth_session._sessions["alive"] = time.time() + 3600
        auth_session.create_session()
        self.assertIn("alive", auth_session._sessions)


if __name__ == "__main__":
    unittest.main()
