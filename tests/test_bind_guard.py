"""tests/test_bind_guard.py — 무토큰 외부 소켓 차단 회귀 (1단계 보안 M-1, 2026-10-10).

배경(점검 실측): 기동 시 보안 게이트(main.py "외부 바인딩 + 무토큰 = 기동 거부")는
VIGENT_HOST **환경변수**만 믿는다 — `uvicorn main:app --host 0.0.0.0` 으로 직접 실행하면
(main.py 자체 docstring 의 예시 명령) 변수가 비어 "루프백"으로 오인하고, 토큰 없이
전 110+ 라우트(/worker/start·/site/config·카메라 스냅샷…)가 LAN 에 열렸다.
→ 요청이 실제 도착한 소켓 주소(ASGI scope["server"] — accept 된 연결의 로컬 주소라 속일
수 없음)를 보고, 무토큰 상태의 비루프백 소켓 요청을 403 으로 차단(+CRITICAL 1회 로그).
웹소켓(ws_auth)도 동일 규칙.

TestClient 의 base_url 호스트가 scope["server"] 로 들어가는 성질을 이용해
외부 인터페이스(192.168.x.x) 도착 상황을 재현한다.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_ENVS = ("VIGENT_API_TOKEN", "VIGENT_ALLOWED_HOSTS", "VIGENT_HOST")


class TestBindGuard(unittest.TestCase):
    def setUp(self):
        self._prev_env = {k: os.environ.get(k) for k in _ENVS}
        for k in _ENVS:
            os.environ.pop(k, None)
        self._prev_token = main._API_TOKEN
        self._prev_hosts = main._ALLOWED_HOSTS

    def tearDown(self):
        main._API_TOKEN = self._prev_token
        main._ALLOWED_HOSTS = self._prev_hosts
        for k, v in self._prev_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_untokened_external_socket_blocked(self):
        """핵심 시나리오: 무토큰 + 외부 인터페이스(192.168.x) 도착 → 403(인증 우회 차단)."""
        main._API_TOKEN = ""
        c = TestClient(main.app, base_url="http://192.168.0.5:8010")
        r = c.get("/status", headers={"Host": "127.0.0.1"})   # Host 헤더를 속여도(curl -H) 소켓은 못 속임
        self.assertEqual(r.status_code, 403)
        self.assertIn("무토큰 외부 노출", r.json()["detail"])

    def test_untokened_loopback_still_works(self):
        """기존 동작 보존: 무토큰 로컬 개발(루프백·testserver 소켓)은 그대로 통과."""
        main._API_TOKEN = ""
        main._ALLOWED_HOSTS = None
        r = TestClient(main.app).get("/status")
        self.assertEqual(r.status_code, 200)

    def test_tokened_external_socket_requires_bearer(self):
        """토큰 모드의 외부 소켓은 기존 규칙 그대로 — 무인증 401, Bearer 200."""
        main._API_TOKEN = "secret-xyz"
        main._ALLOWED_HOSTS = None
        c = TestClient(main.app, base_url="http://192.168.0.5:8010")
        self.assertEqual(c.get("/status").status_code, 401)
        r = c.get("/status", headers={"Authorization": "Bearer secret-xyz"})
        self.assertEqual(r.status_code, 200)

    def test_healthz_also_blocked_when_untokened_external(self):
        """[주의 명시] M-1 차단은 _AUTH_EXEMPT 보다 먼저다 — 무토큰 외부 노출은 /healthz 도 닫는다
        (이 상태 자체가 설정 오류라서 열어 둘 정상 경로가 없다)."""
        main._API_TOKEN = ""
        c = TestClient(main.app, base_url="http://192.168.0.5:8010")
        self.assertEqual(c.get("/healthz").status_code, 403)

    def test_ws_untokened_external_socket_blocked(self):
        """웹소켓도 동일 규칙 — 무토큰 외부 소켓 핸드셰이크 거부(카메라 중계 보호).
        TestClient 는 WS scope["server"] 를 testserver 로 고정하므로(실측) 검사 함수를 직접 검증한다."""
        import types

        import ws_auth

        def fake(server):
            return types.SimpleNamespace(scope={"server": server}, headers={})

        self.assertFalse(ws_auth._handshake_source_ok(fake(("192.168.0.5", 8010))))   # 외부 소켓 → 거부
        self.assertTrue(ws_auth._handshake_source_ok(fake(("127.0.0.1", 8010))))      # 루프백 → 통과
        self.assertTrue(ws_auth._handshake_source_ok(fake(("testserver", 80))))       # TestClient → 통과
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"                                 # 토큰 모드면 M-1 검사 없음
        try:
            self.assertTrue(ws_auth._handshake_source_ok(fake(("192.168.0.5", 8010))))
        finally:
            os.environ.pop("VIGENT_API_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
