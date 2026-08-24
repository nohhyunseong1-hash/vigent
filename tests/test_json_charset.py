"""[B-enc] JSON 응답 한글 깨짐 회귀 방지.

배경(2026-08-20 확정): /health 의 `privacy.note` 가 PowerShell 에서
"BitLocker 議고쉶뒗 愿由ъ옄..." 로 깨져 보였다. 서버는 올바른 UTF-8 을 보내지만
content-type 에 charset 이 없어, 한국어 Windows 의 PowerShell 5.1 Invoke-RestMethod 가
시스템 ANSI(CP949)로 디코드한 것이다 — 개발 PC 에서 관측된 뒤 **새 기계인 현장 노트북에서도
그대로 재현**돼 환경 탓이 아님이 확정됐다.

현장에서 /health 로 상태를 읽는데 정작 원인 설명 문자열이 안 읽히면 진단이 불가능하다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

from web_util import json_charset_header  # noqa: E402


class TestJsonCharsetHeader(unittest.TestCase):

    def test_plain_json_gets_charset(self):
        self.assertEqual(json_charset_header("application/json"),
                         "application/json; charset=utf-8")

    def test_already_has_charset_is_untouched(self):
        for ct in ("application/json; charset=utf-8",
                   "application/json;charset=UTF-8",
                   "application/json; CHARSET=euc-kr"):
            self.assertIsNone(json_charset_header(ct), ct)

    def test_non_json_untouched(self):
        for ct in ("text/html", "text/plain", "image/jpeg",
                   "application/octet-stream", "multipart/form-data", ""):
            self.assertIsNone(json_charset_header(ct), ct)

    def test_json_subtype_covered(self):
        self.assertEqual(json_charset_header("application/json+ld"),
                         "application/json+ld; charset=utf-8")


class TestResponseIsDecodableAsCp949Trap(unittest.TestCase):
    """미들웨어를 실제 응답에 걸었을 때 헤더가 붙는지(종단)."""

    def test_middleware_sets_charset_on_real_response(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.middleware("http")
        async def _charset(request, call_next):
            resp = await call_next(request)
            fixed = json_charset_header(resp.headers.get("content-type", ""))
            if fixed:
                resp.headers["content-type"] = fixed
            return resp

        @app.get("/k")
        def k():
            return JSONResponse({"note": "BitLocker 조회는 관리자 권한이 필요하다"})

        @app.get("/h")
        def h():
            from fastapi.responses import HTMLResponse
            return HTMLResponse("<p>한글</p>")

        c = TestClient(app)
        r = c.get("/k")
        self.assertIn("charset=utf-8", r.headers["content-type"].lower())
        # charset 을 신뢰해 디코드하면 원문이 그대로 나온다
        self.assertIn("조회는", r.json()["note"])
        # 명시가 없었다면 CP949 로 읽혀 깨졌을 바이트임을 함께 확인(회귀 시 이 단정이 의미를 갖는다)
        self.assertIn("議고쉶", r.content.decode("cp949", "replace"))

        # HTML 응답은 미들웨어가 건드리지 않는다(Starlette 이 이미 charset 을 붙여 준다)
        self.assertTrue(c.get("/h").headers["content-type"].startswith("text/html"))


if __name__ == "__main__":
    unittest.main()
