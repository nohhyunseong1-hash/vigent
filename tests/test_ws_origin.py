"""tests/test_ws_origin.py — WS 핸드셰이크 Origin·Host 검사 회귀 (1단계 보안 H-5, 2026-10-10).

배경(점검 실측): 웹소켓은 브라우저 동일 출처 정책(CORS)을 받지 않는다 — 기본 모드(로컬
127.0.0.1·무토큰)에서 관리자가 악성 웹페이지를 하나 열면, 그 페이지의 JS 가
`new WebSocket("ws://127.0.0.1:8010/tapo/ws?src=cam1")` 로 몰래 접속해 **라이브 카메라 영상을
외부로 중계**할 수 있었다(Cross-Site WebSocket Hijacking). HTTP 쪽의 Host 허용목록(DNS
rebinding 방어, main._auth_guard)도 websocket scope 에는 적용되지 않았고, 세션 쿠키는
SameSite=Lax 라 WS 핸드셰이크를 막지 못해 토큰 모드에서도 같은 구멍이 남았다.
ws_auth 에 ① Host 허용목록 ② (브라우저 요청이면) Origin 허용목록 검사를 추가한 수정을
회귀 잠금한다. 기존 test_ws_auth.py 의 토큰 동작(쿼리·헤더·쿠키·미설정 통과)은 그대로다.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.testclient import WebSocketDisconnect  # noqa: E402

_ENVS = ("VIGENT_API_TOKEN", "VIGENT_ALLOWED_HOSTS", "VIGENT_WS_ALLOW_ORIGINS", "VIGENT_HOST")


class TestWsOrigin(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev = {k: os.environ.get(k) for k in _ENVS}
        for k in _ENVS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _expect_reject(self, **kw):
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/tapo/ws", **kw):
                pass
        self.assertEqual(cm.exception.code, 1008)

    # ── 무토큰(기본 로컬) 모드 ──────────────────────────────────────────────
    def test_cross_site_origin_rejected_without_token(self):
        """핵심 공격 시나리오: 무토큰 로컬 모드 + 외부 사이트 Origin → 거부."""
        self._expect_reject(headers={"Origin": "https://evil.example"})

    def test_null_origin_rejected(self):
        """샌드박스 iframe 등이 보내는 Origin: null 도 허용목록 밖 → 거부."""
        self._expect_reject(headers={"Origin": "null"})

    def test_same_origin_browser_accepted(self):
        """허용목록 호스트(127.0.0.1)에서 열린 페이지의 WS 는 기존대로 통과."""
        with self.client.websocket_connect("/tapo/ws", headers={"Origin": "http://127.0.0.1:8010"}):
            pass

    def test_non_browser_client_without_origin_accepted(self):
        """Origin 없는 비브라우저 클라이언트(curl 등)는 Host 검사만 — 기존 동작 불변."""
        with self.client.websocket_connect("/tapo/ws"):
            pass

    def test_spoofed_host_rejected(self):
        """DNS rebinding 꼴: Host 가 허용목록 밖이면 거부(HTTP 미들웨어와 동일 기준)."""
        self._expect_reject(headers={"Host": "evil.example"})

    # ── 토큰 모드 ───────────────────────────────────────────────────────────
    def test_correct_token_with_evil_origin_still_rejected(self):
        """토큰이 맞아도 교차 사이트 Origin 이면 거부 — 쿠키 편승(Lax 는 WS 를 안 막음) 차단."""
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        self._expect_reject(headers={"Origin": "https://evil.example"},
                            params={"token": "secret-xyz"})

    def test_correct_token_same_origin_accepted(self):
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        with self.client.websocket_connect("/tapo/ws",
                                           headers={"Origin": "http://localhost:8010",
                                                    "Authorization": "Bearer secret-xyz"}):
            pass  # (쿼리 ?token= 은 [L-3] 폐지 — Bearer 헤더로 검증)

    # ── 예외 구성 ───────────────────────────────────────────────────────────
    def test_explicit_allowlist_env_is_honored(self):
        """VIGENT_ALLOWED_HOSTS 로 명시한 호스트의 Origin·Host 는 허용(TestClient Host 는 testserver 라 함께 등재)."""
        os.environ["VIGENT_ALLOWED_HOSTS"] = "cctv.example,testserver"
        with self.client.websocket_connect("/tapo/ws", headers={"Origin": "https://cctv.example"}):
            pass
        self._expect_reject(headers={"Origin": "https://evil.example"})

    def test_ws_allow_origins_escape_hatch(self):
        """특수 구성(파일럿 등)용 VIGENT_WS_ALLOW_ORIGINS — 지정한 출처만 추가 허용."""
        os.environ["VIGENT_WS_ALLOW_ORIGINS"] = "kiosk.example"
        with self.client.websocket_connect("/tapo/ws", headers={"Origin": "http://kiosk.example"}):
            pass


if __name__ == "__main__":
    unittest.main()
