"""엔드포인트 스모크 (P2-14) — P1-7 라우터 분할 회귀 잠금.

routers/ 로 분할된 뒤에도 핵심 경로가 그대로 응답하는지, 특히
`/{theme}` 캐치올이 `/health` 같은 리터럴 경로를 가리지 않는지 확인한다.
동작 변경 감시용 — 새 라우트 추가가 아니라 기존 동작 고정이 목적.

[Z-3, 2026-08-10] office/sports 기능 영구 삭제(제품 방향 확정 — 산업안전 CCTV 전용) —
`_theme_gate` 미들웨어는 office/sports 차단 용도로만 존재해 함께 제거됨. `/office/*` 는
이제 게이트가 아니라 라우트 자체가 없어서 404다(아래 테스트로 확인).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestEndpointsSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()   # startup 이벤트(기본 테마 로드) 발화

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_health_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "ok")

    def test_capabilities_ok(self):
        r = self.client.get("/system/capabilities")
        self.assertEqual(r.status_code, 200)
        self.assertIn("pipeline", r.json())

    def test_root_ok(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("brand"), "VIGENT")

    def test_landing_pages(self):
        for path in ("/home", "/hub"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_catchall_does_not_shadow_health(self):
        # /{theme} 캐치올이 /health 를 삼키면 테마 HTML 이 오고 JSON status 가 없다.
        r = self.client.get("/health")
        self.assertEqual(r.headers.get("content-type", "").split(";")[0], "application/json")
        self.assertEqual(r.json().get("status"), "ok")

    def test_theme_page_via_catchall(self):
        # GET /safety → /{theme} 캐치올로 safety 테마 페이지(HTML) 200.
        r = self.client.get("/safety")
        self.assertEqual(r.status_code, 200)

    def test_removed_office_route_is_gone(self):
        # [Z-3] office 라우트 자체가 삭제됐으므로 404(게이트가 아니라 라우트 부재).
        self.assertEqual(self.client.get("/office/trend").status_code, 404)


if __name__ == "__main__":
    unittest.main()
