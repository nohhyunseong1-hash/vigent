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
from _isolate import isolate_alerts  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestEndpointsSmoke(unittest.TestCase):

    # ★[2026-08-20] 인증 환경 격리 — 이 클래스는 "무인증 기본 동작"을 검증한다.
    #   배포 설정이 된 기계에는 .env 에 VIGENT_API_TOKEN 이 있고, main 이 import 시점에
    #   그것을 읽어 전 라우트에 Bearer 를 강제한다 → 여기 테스트가 전부 401 로 깨진다.
    #   CI 는 .env 가 없어 초록인데 실기계는 빨강 = "게이트가 통과했다"는 조용한 거짓말이 된다
    #   (현장 노트북에서 실제로 11건 실패 발생). 인증 자체는 test_security_gate.py ·
    #   test_ws_auth.py · test_browser_session_auth.py 가 따로 검증한다.
    #   main._API_TOKEN 은 요청마다 전역 조회라 monkeypatch 로 격리된다(test_security_gate 관례).
    @classmethod
    def setUpClass(cls):
        cls._saved_token = main._API_TOKEN
        main._API_TOKEN = ""                  # 무인증 기본 동작으로 고정
        # ★[4단계 ④] startup 이 alert_notify 전송기를 실제 dispatcher 에 배선한다 — 그 배선이
        #   운영 data/alert_queue.db 에 시험 행을 남겼다(실측 2026-08-28). 큐·전송기를 격리한다.
        cls.addClassCleanup(isolate_alerts())
        cls.client = TestClient(main.app)
        cls.client.__enter__()   # startup 이벤트(기본 테마 로드) 발화

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        main._API_TOKEN = cls._saved_token

    def test_health_ok(self):
        # [B2] status 계약: "ok" 고정 → 실판정(healthy|degraded|unhealthy).
        # [B4] 예열 중에는 starting + HTTP 503 — "아직 준비 안 됨"을 정직하게 알린다.
        #   테스트 환경은 예열이 진행 중일 수 있으므로 두 경우를 모두 허용한다.
        r = self.client.get("/health")
        self.assertIn(r.status_code, (200, 503))
        self.assertIn(r.json().get("status"), ("healthy", "degraded", "unhealthy", "starting"))
        self.assertIn("cameras", r.json())      # 검출 생존 필드가 반드시 실린다
        self.assertIn("phase", r.json())        # 예열 단계가 반드시 실린다

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
        self.assertIn(r.json().get("status"),
                      ("healthy", "degraded", "unhealthy", "starting"))   # [B2]3단계 + [B4]starting

    def test_theme_page_via_catchall(self):
        # GET /safety → /{theme} 캐치올로 safety 테마 페이지(HTML) 200.
        r = self.client.get("/safety")
        self.assertEqual(r.status_code, 200)

    def test_removed_office_route_is_gone(self):
        # [Z-3] office 라우트 자체가 삭제됐으므로 404(게이트가 아니라 라우트 부재).
        self.assertEqual(self.client.get("/office/trend").status_code, 404)

    def test_theme_whitelist_rejects_invalid_names(self):
        # [S2-수정] {theme} 화이트리스트(^[a-z0-9_-]+$) — 대문자·특수문자 등은 404
        # (".." 자체는 HTTP 클라이언트가 요청 전에 경로를 정규화해버려 여기서 직접 검증하기
        #  어렵다 — 그 경로는 tests/test_vision_loader_theme.py 에서 함수 단위로 확인한다).
        for bad in ("SAFETY", "safety;drop", "safety.."):
            with self.subTest(theme=bad):
                self.assertEqual(self.client.get(f"/{bad}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
