"""tests/test_ws_auth.py — /tapo/ws 토큰 인증 회귀 (P0 수정).

main._auth_guard 는 `@app.middleware("http")` 로 등록되어 HTTP scope 에만 적용되고
websocket scope 에는 적용되지 않는다 — 그 결과 /tapo/ws 는 VIGENT_API_TOKEN 검사를
그대로 우회했다(docs/COMMERCIALIZATION_AUDIT.md Phase1 P0). ws_auth.ws_token_ok 를
/tapo/ws 핸들러 진입부에 배선한 수정을 회귀 잠금:
  ① VIGENT_API_TOKEN 설정 + 토큰 없음/오답 → 핸드셰이크 거부(1008)
  ② VIGENT_API_TOKEN 설정 + 올바른 토큰(쿼리 또는 헤더) → 핸드셰이크 성공(accept 도달)
  ③ VIGENT_API_TOKEN 미설정 → 기존 동작 불변(무인증 통과)

go2rtc(localhost:1984)는 테스트 환경에 없어 인증 통과 후 업스트림 연결은 실패하지만,
그 실패는 tapo_ws 내부 `except Exception: pass`(연결 종료/실패 시 조용히 닫음)에서 이미
흡수되므로, 이 테스트는 핸드셰이크(accept) 성공 여부만으로 인증 통과를 판정하면 충분하다.
ws_auth.ws_token_ok 는 main._API_TOKEN 이 아니라 환경변수 VIGENT_API_TOKEN 을 직접 읽으므로
(모듈 간 무의존 설계), 여기서도 os.environ 을 직접 조작한다.
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


class TestWsAuth(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")

    def tearDown(self):
        if self._prev_token is None:
            os.environ.pop("VIGENT_API_TOKEN", None)
        else:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token

    def test_ws_rejects_missing_token_when_required(self):
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/tapo/ws"):
                pass
        self.assertEqual(cm.exception.code, 1008)

    def test_ws_rejects_wrong_token(self):
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/tapo/ws?token=wrong"):
                pass
        self.assertEqual(cm.exception.code, 1008)

    def test_ws_accepts_correct_token_via_query(self):
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        with self.client.websocket_connect("/tapo/ws?token=secret-xyz"):
            pass  # 예외 없이 진입 = accept() 도달(인증 통과)

    def test_ws_accepts_correct_token_via_header(self):
        os.environ["VIGENT_API_TOKEN"] = "secret-xyz"
        with self.client.websocket_connect("/tapo/ws", headers={"Authorization": "Bearer secret-xyz"}):
            pass

    def test_ws_unchanged_when_token_unset(self):
        os.environ.pop("VIGENT_API_TOKEN", None)
        with self.client.websocket_connect("/tapo/ws"):
            pass  # 토큰 미설정 = 기존 동작(무인증 통과) 불변


if __name__ == "__main__":
    unittest.main()
