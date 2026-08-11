"""tests/test_browser_session_auth.py — [S3-후속1] 브라우저 로그인/세션 쿠키 회귀.

[S3 엣지박스 리허설]에서 발견: VIGENT_REQUIRE_TOKEN=1 모드는 Authorization 헤더가 없는
평범한 브라우저 페이지 이동을 전부 401로 막았다(대시보드 자체가 무용지물). 이 테스트는
그 해결책(auth_session.py + main.py 의 /login·/logout·_auth_guard 쿠키 폴백)을 잠근다:
  ① 로그인 폼(GET /login) 무인증 접근 가능
  ② 올바른 토큰으로 로그인 → 세션 쿠키 발급 → 이후 Authorization 헤더 없이도 통과
  ③ 틀린 토큰 → 401, 쿠키 미발급
  ④ 반복 실패 → 잠금(429)
  ⑤ 로그아웃 → 세션 무효화
  ⑥ API/AJAX 요청(Accept: text/html 아님)은 기존과 동일하게 401 JSON(회귀 방지) — 페이지
    이동(GET + Accept: text/html)만 /login 으로 리다이렉트
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import auth_session  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestBrowserSessionAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._tok, self._hosts = main._API_TOKEN, main._ALLOWED_HOSTS
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None
        auth_session._sessions.clear()
        auth_session._failures.clear()
        auth_session._locked_until.clear()

    def tearDown(self):
        main._API_TOKEN, main._ALLOWED_HOSTS = self._tok, self._hosts
        auth_session._sessions.clear()
        auth_session._failures.clear()
        auth_session._locked_until.clear()

    def test_login_page_reachable_without_auth(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.text)

    def test_browser_page_without_auth_redirects_to_login(self):
        r = self.client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("/login"))

    def test_api_request_without_auth_still_gets_401_json(self):
        r = self.client.get("/status")   # Accept 기본값(TestClient) = */* → JSON 401 유지(회귀 방지)
        self.assertEqual(r.status_code, 401)

    def test_correct_login_sets_session_cookie_and_grants_access(self):
        r = self.client.post("/login", data={"token": "secret-xyz", "next": "/"},
                              follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn(auth_session.SESSION_COOKIE, r.cookies)
        r2 = self.client.get("/status")   # Authorization 헤더 없이 쿠키만으로 통과
        self.assertNotEqual(r2.status_code, 401)

    def test_wrong_token_login_rejected_no_cookie(self):
        r = self.client.post("/login", data={"token": "wrong", "next": "/"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn(auth_session.SESSION_COOKIE, r.cookies)

    def test_repeated_failures_lock_out(self):
        for _ in range(auth_session._LOCKOUT_THRESHOLD):
            self.client.post("/login", data={"token": "wrong", "next": "/"})
        r = self.client.post("/login", data={"token": "secret-xyz", "next": "/"})
        self.assertEqual(r.status_code, 429)   # 잠금 중이면 올바른 토큰도 거부

    def test_logout_invalidates_session(self):
        self.client.post("/login", data={"token": "secret-xyz", "next": "/"})
        r = self.client.post("/logout", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        r2 = self.client.get("/status")
        self.assertEqual(r2.status_code, 401)   # 로그아웃 후 다시 차단

    def test_open_redirect_blocked(self):
        r = self.client.get("/login", params={"next": "//evil.example.com"})
        self.assertNotIn("evil.example.com", r.text)


if __name__ == "__main__":
    unittest.main()
