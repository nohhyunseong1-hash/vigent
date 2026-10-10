"""tests/test_cookie_secure.py — 세션 쿠키 Secure 플래그(HTTPS 조건부) 회귀 (1단계 보안 M-6, 2026-10-10).

배경(점검 실측): 로그인 세션 쿠키가 httponly·samesite=lax 는 있는데 Secure 가 없어,
TLS 배포(docs/TLS_DEPLOYMENT.md)에서도 브라우저가 평문 HTTP 요청에 쿠키를 실을 수 있었다
(LAN 도청으로 세션 탈취). 단 현행 파일럿은 HTTP 운용이라 **무조건 Secure 를 켜면 로그인
자체가 깨진다** → HTTPS 로 로그인한 경우(uvicorn 직접 TLS = scheme https, 또는 역프록시의
X-Forwarded-Proto: https)에만 Secure 를 붙이고, HTTP 로그인은 기존 그대로 둔다.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import auth_session  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestCookieSecure(unittest.TestCase):
    def setUp(self):
        self._prev_token = main._API_TOKEN
        self._prev_env = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)
        main._API_TOKEN = "secret-xyz"
        auth_session._sessions.clear()
        if hasattr(auth_session, "_failures"):
            auth_session._failures.clear()   # 다른 테스트의 로그인 실패 기록이 잠금(429)으로 번지지 않게

    def tearDown(self):
        main._API_TOKEN = self._prev_token
        auth_session._sessions.clear()
        if self._prev_env is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_env

    def _login(self, client, **kw):
        return client.post("/login", data={"token": "secret-xyz", "next": "/"},
                           follow_redirects=False, **kw)

    def test_http_login_works_without_secure(self):
        """현행 HTTP 운용 보존: 로그인 성공 + 쿠키 발급 + Secure 플래그 없음."""
        c = TestClient(main.app)
        r = self._login(c)
        self.assertEqual(r.status_code, 303)
        set_cookie = r.headers.get("set-cookie", "")
        self.assertIn(auth_session.SESSION_COOKIE, set_cookie)
        self.assertNotIn("secure", set_cookie.lower())
        self.assertEqual(c.get("/status").status_code, 200)   # 쿠키로 보호 라우트 접근(로그인 동작 확인)

    def test_https_login_sets_secure(self):
        """uvicorn 직접 TLS(scheme=https) → Secure 플래그."""
        c = TestClient(main.app, base_url="https://testserver")
        set_cookie = self._login(c).headers.get("set-cookie", "")
        self.assertIn(auth_session.SESSION_COOKIE, set_cookie)
        self.assertIn("secure", set_cookie.lower())

    def test_forwarded_proto_https_sets_secure(self):
        """역프록시(Caddy/nginx) 뒤 — X-Forwarded-Proto: https 로도 Secure."""
        c = TestClient(main.app)
        set_cookie = self._login(c, headers={"X-Forwarded-Proto": "https"}).headers.get("set-cookie", "")
        self.assertIn("secure", set_cookie.lower())


if __name__ == "__main__":
    unittest.main()
