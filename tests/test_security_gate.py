"""보안 게이트 테스트 (item3 — 파일럿 보안).

main._auth_guard 미들웨어가
  ① Host 허용목록 밖 요청을 403 으로 차단(DNS-rebinding 방어, CODE_REVIEW §3.3)
  ② VIGENT_API_TOKEN 설정 시 Bearer 를 강제(미설정 경로 예외 유지)
하는지 회귀 잠금. 미들웨어는 요청마다 실행되므로 모델 로드(startup) 불필요.
_ALLOWED_HOSTS·_API_TOKEN 은 모듈 전역 → 런타임 조회라 monkeypatch 로 케이스 격리.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestSecurityGate(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._tok, self._hosts = main._API_TOKEN, main._ALLOWED_HOSTS

    def tearDown(self):
        main._API_TOKEN, main._ALLOWED_HOSTS = self._tok, self._hosts

    def test_host_allowlist_blocks_foreign(self):
        main._ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
        r = self.client.get("/health", headers={"host": "evil.example.com"})
        self.assertEqual(r.status_code, 403)               # DNS-rebinding 차단

    def test_host_allowlist_allows_loopback_with_port(self):
        main._ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
        r = self.client.get("/health", headers={"host": "127.0.0.1:8010"})
        self.assertNotEqual(r.status_code, 403)            # 포트 제거 후 허용

    def test_host_check_skipped_when_none(self):
        main._ALLOWED_HOSTS = None                          # 외부바인딩+미지정 = 검사 스킵
        r = self.client.get("/health", headers={"host": "anything.example.com"})
        self.assertNotEqual(r.status_code, 403)

    def test_token_required_when_set(self):
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None                          # 토큰만 격리 검증
        self.assertEqual(self.client.get("/status").status_code, 401)          # Bearer 없음
        r = self.client.get("/status", headers={"Authorization": "Bearer secret-xyz"})
        self.assertNotEqual(r.status_code, 401)             # 올바른 Bearer → 통과

    def test_token_wrong_bearer_rejected(self):
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None
        r = self.client.get("/status", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)

    def test_health_exempt_from_token(self):
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None
        self.assertNotEqual(self.client.get("/health").status_code, 401)       # /health 는 인증 예외


if __name__ == "__main__":
    unittest.main()
