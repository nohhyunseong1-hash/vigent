"""tests/test_healthz.py — /healthz 신설·/health 보호 회귀 (1단계 보안 M-2, 2026-10-10).

배경(점검 실측): /health 는 무인증 면제(main._AUTH_EXEMPT)인데 응답에 GPU 모델·VRAM·
모델별 SHA·카메라 id·기동 경고(예외 문자열)·경보 큐 상태까지 담았다 — 외부 바인딩에서
배포 구성이 통째로 공짜 지문이었고, 에러 문자열 계열 필드는 시간이 지나며 비밀이 섞여들기
쉬운 자리다. → 무인증 면제를 /healthz(status·phase 만)로 교체하고 /health 는 토큰 뒤로.
워치독(watchdog.sh)·포터블 대기(portable_wait.py)·서비스 점검(service_status.ps1·
verify_service_reinstall.ps1 — .env 토큰 Bearer)·문서(DEPLOYMENT.md)도 함께 바꿨다.

검증: ① /healthz 는 토큰 모드에서도 무인증 접근 가능 ② 본문은 status·phase 두 키뿐
(민감 키 부재) ③ 판정·상태코드가 /health 와 동일 ④ /health 는 토큰 모드에서 401,
Bearer·쿠키로는 접근 가능(화면·스크립트 경로 보존).
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestHealthz(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)
        self._prev_main_token = main._API_TOKEN
        self._prev_hosts = main._ALLOWED_HOSTS

    def tearDown(self):
        main._API_TOKEN = self._prev_main_token
        main._ALLOWED_HOSTS = self._prev_hosts
        if self._prev_token is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token

    def _token_mode(self):
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None

    def test_healthz_minimal_body_no_sensitive_keys(self):
        r = self.client.get("/healthz")
        body = r.json()
        self.assertEqual(set(body.keys()), {"status", "phase"})
        # /health 가 담는 민감 계열 키가 여기 없어야 한다
        for k in ("models", "gpu", "cameras", "warnings", "alerts", "notify", "relay", "llm"):
            self.assertNotIn(k, body)

    def test_healthz_matches_health_verdict(self):
        """판정(status)·HTTP 코드가 /health 와 동일해야 워치독 대체가 성립한다."""
        hz = self.client.get("/healthz")
        h = self.client.get("/health")       # 무토큰 모드라 접근 가능
        self.assertEqual(hz.status_code, h.status_code)
        self.assertEqual(hz.json()["status"], h.json()["status"])
        self.assertEqual(hz.json()["phase"], h.json().get("phase"))

    def test_token_mode_healthz_open_health_protected(self):
        self._token_mode()
        self.assertNotEqual(self.client.get("/healthz").status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 401)

    def test_token_mode_health_with_bearer_ok(self):
        self._token_mode()
        r = self.client.get("/health", headers={"Authorization": "Bearer secret-xyz"})
        self.assertNotEqual(r.status_code, 401)
        self.assertIn("status", r.json())    # 전체 본문 접근 보존(화면·점검 스크립트 경로)


if __name__ == "__main__":
    unittest.main()
