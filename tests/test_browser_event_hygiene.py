"""[CODE_REVIEW M8-5·M8-6·M8-7] 시연 화면(브라우저)이 서버 기록에 남기는 것의 위생.

M8-7: POST /recognition/log 는 규칙 화이트리스트(위험성평가 규칙 지식베이스 + 서버 규칙) 밖이면 400 —
      실측: 프론트 디버그 텔레메트리(coord_*)·정체불명 rule='t' 194행이 안전 이벤트 로그에 섞여 있었다. 기록에는 source 꼬리표.
M8-6: /zone/intrusion 증거 JPEG 는 브라우저가 보낸 **원본 프레임 그대로**, 오버레이(박스·구역)는 별도 *_overlay.png.
M8-5: 브라우저 PPE 휴리스틱은 '참고(서버 판정 아님)' 문구이고 통보 경로(getPpeIssues)는 서버 판정(ppe_yolo)만 쓴다(정적 검사).
"""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import data_engine  # noqa: E402
import main  # noqa: E402
from _isolate import isolate_alerts, isolate_data_dirs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from routers import zone as zone_router  # noqa: E402

_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class RecognitionLogWhitelist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        cls.addClassCleanup(isolate_data_dirs())
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main._API_TOKEN = cls._saved_token

    def test_rejects_debug_and_unknown_rules(self):
        for bad in ("coord_mismatch", "coord_event", "t", "", "debug"):
            r = self.client.post("/recognition/log", json={"rule": bad, "level": "debug", "note": "x"})
            self.assertEqual(r.status_code, 400, f"거부돼야 한다: {bad!r}")

    def test_accepts_known_rule_and_tags_source(self):
        r = self.client.post("/recognition/log", json={"rule": "zone_intrusion", "level": "high", "note": "t"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("source"), "browser")
        ev = data_engine.list_events(limit=5)
        self.assertTrue(ev and ev[0]["rule"] == "zone_intrusion" and ev[0].get("source") == "browser")


class _FakeDispatcher:
    def channels_configured(self):
        return True


class IntrusionEvidenceOverlay(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.addCleanup(isolate_data_dirs())
        self._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        self.addCleanup(setattr, main, "_API_TOKEN", self._saved_token)
        p = mock.patch.dict(zone_router.STATE, {zone_router.DEFAULT_THEME: {"agents": {"Dispatcher": _FakeDispatcher()}}})
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(main.app)

    def test_evidence_is_raw_frame_and_overlay_saved_separately(self):
        frame_b64 = base64.b64encode(_PNG_1x1).decode()
        overlay_b64 = "data:image/png;base64," + base64.b64encode(_PNG_1x1 + b"OVERLAY").decode()
        r = self.client.post("/zone/intrusion", json={
            "image_base64": frame_b64, "overlay_base64": overlay_b64, "people": 1,
            "reasons": ["몸통 진입"], "zone": "위험구역A", "cam": "cam-t", "source": "browser"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        ev = data_engine._ROOT / j["evidence"]
        self.assertTrue(ev.exists(), "증거 파일이 있어야 한다")
        self.assertEqual(ev.read_bytes(), _PNG_1x1, "증거는 브라우저가 보낸 원본 프레임 그대로(합성 없음)")
        self.assertTrue(j["overlay"] and j["overlay"].endswith("_overlay.png"), j)
        ov = data_engine._ROOT / j["overlay"]
        self.assertTrue(ov.exists() and ov.parent == ev.parent, "오버레이는 증거 옆 별도 파일")
        self.assertEqual(ov.read_bytes(), _PNG_1x1 + b"OVERLAY")
        rec = data_engine.list_events(limit=1)[0]
        self.assertEqual(rec.get("source"), "browser")

    def test_without_overlay_field_is_fine(self):
        r = self.client.post("/zone/intrusion", json={"people": 1, "reasons": ["x"], "zone": "Z", "cam": "cam-t"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["overlay"])


class FrontendHygieneStatic(unittest.TestCase):
    def test_realtime_core_no_debug_log_posts_and_reference_only_ppe(self):
        js = (_ROOT / "vigent-core" / "static" / "realtime_core.js").read_text(encoding="utf-8")
        # (큰 파일이라 assertIn 대신 count — 실패 시 파일 전체가 출력되지 않게)
        self.assertEqual(js.count("rule:'coord_"), 0, "디버그 텔레메트리를 /recognition/log 로 보내면 안 된다")
        self.assertEqual(js.count("미착용 의심"), 0, "브라우저 휴리스틱은 '참고(서버 판정 아님)' 문구")
        self.assertEqual(js.count("source!=='ppe_yolo'"), 1, "getPpeIssues 는 서버 판정만")
        self.assertGreaterEqual(js.count("overlay_base64"), 1, "증거 원본 + 오버레이 별도 전송")
        page = (_ROOT / "themes" / "safety" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page.count("source:'browser'"), 3, "페이지 자체 기록 3경로에 출처 꼬리표")


if __name__ == "__main__":
    unittest.main()
