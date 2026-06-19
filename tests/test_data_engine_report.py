"""6단계 검증 — 데이터엔진(증거·로그 저장/집계) + 리포트(목록·다시열기·표준양식)"""
import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import data_engine  # noqa: E402
import vision_loader  # noqa: E402
from agents import build_agents  # noqa: E402

# 1x1 흰 픽셀 JPEG (base64) — 증거 프레임 저장 테스트용
_PIX = ("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////"
        "////////////////////////////////////////////////////////////2wBDAf//"
        "////////////////////////////////////////////////////////////////////"
        "////////wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAAAv/EABQQAQAA"
        "AAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAA"
        "AAAAAP/aAAwDAQACEQMRAD8AfwH/2Q==")


class TestDataEngine(unittest.TestCase):
    def test_log_event_writes_record_and_frame(self):
        rec = data_engine.log_event("zone_intrusion", "high", 60, site="t", image_data_url=_PIX)
        self.assertEqual(rec["rule"], "zone_intrusion")
        self.assertIsNotNone(rec["evidence"])                  # 증거 경로 생성
        self.assertTrue((ROOT / rec["evidence"]).exists())     # 실제 파일 저장됨

    def test_log_without_image_is_ok(self):
        rec = data_engine.log_event("ppe_missing", "medium", 30)
        self.assertIsNone(rec["evidence"])                     # 이미지 없이도 무중단

    def test_aggregate_counts(self):
        before = {d["rule"]: d["count"] for d in data_engine.aggregate(hours=24)}
        data_engine.log_event("guard_bypass", "critical", 100)
        after = {d["rule"]: d["count"] for d in data_engine.aggregate(hours=24)}
        self.assertEqual(after.get("guard_bypass", 0), before.get("guard_bypass", 0) + 1)


class TestReport(unittest.TestCase):
    def setUp(self):
        cfg = vision_loader.load_vision("safety")
        self.scribe = build_agents(cfg)["Scribe"]

    def test_standard_form_flow_in_html(self):
        html = self.scribe.generate([{"rule": "zone_intrusion", "count": 5}], save=False)["html"]
        # 한국 표준 양식 흐름 4단계가 보여야 함
        for token in ("위험요인 식별", "빈도", "강도", "위험성", "감소대책", "산업안전보건법"):
            self.assertIn(token, html)

    def test_save_list_reopen(self):
        out = self.scribe.generate([{"rule": "fall_suspected", "count": 2}], site="저장테스트", save=True)
        aid = Path(out["saved_path"]).stem
        items = self.scribe.list_saved()
        self.assertTrue(any(i["id"] == aid for i in items))    # 목록에 나타남
        self.assertIsNotNone(self.scribe.load_html(aid))       # 다시열기 가능

    def test_load_html_rejects_path_traversal(self):
        self.assertIsNone(self.scribe.load_html("../../etc/passwd"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
