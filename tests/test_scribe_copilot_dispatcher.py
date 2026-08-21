"""4단계 검증 — Scribe(보고서)·Copilot(근거)·Dispatcher(알림)"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import vision_loader  # noqa: E402
from agents import build_agents  # noqa: E402


class TestStep4(unittest.TestCase):
    def setUp(self):
        cfg = vision_loader.load_vision("safety")
        self.agents = build_agents(cfg)

    # ── Copilot: 근거에 출처 포함(§9) ──
    def test_copilot_citation_has_source(self):
        c = self.agents["Copilot"].cite("zone_intrusion")
        self.assertFalse(c["fallback"])
        self.assertTrue(c["citations"])
        for cite in c["citations"]:
            self.assertTrue(cite["source"], "인용에 출처(source)가 있어야 함")

    def test_copilot_unknown_rule_fallback(self):
        c = self.agents["Copilot"].cite("does_not_exist")
        self.assertTrue(c["fallback"])     # 빈손 대신 검토 안내(무중단)
        self.assertTrue(c["citations"])

    # ── Scribe: 위험성평가표 + 근거 삽입 + HTML ──
    def test_scribe_assessment_with_citations(self):
        out = self.agents["Scribe"].generate(
            [{"rule": "zone_intrusion", "count": 5}, {"rule": "ppe_missing", "count": 9}],
            site="A현장", process="조립", save=False, mode="quantitative")
        a = out["assessment"]
        self.assertEqual(a["summary"]["총항목"], 2)
        self.assertEqual(a["status"], "draft")
        self.assertTrue(a["review_required"])
        # 첫 행에 법령 인용이 실제로 삽입됐는지
        self.assertTrue(a["rows"][0]["citations"])
        self.assertIn("산업안전보건법", a["rows"][0]["관련근거"])

    def test_scribe_html_renders(self):
        out = self.agents["Scribe"].generate([{"rule": "ppe_missing", "count": 2}],
                                             save=False, mode="quantitative")
        html = out["html"]
        self.assertIn("위험성평가서", html)
        self.assertIn("인쇄 / PDF로 저장", html)
        self.assertIn("산업안전보건법", html)   # 근거가 본문에 표기

    def test_scribe_checklist_mode(self):
        # 기본 mode=checklist — 체크리스트 양식 산출
        out = self.agents["Scribe"].generate([{"rule": "ppe_missing", "count": 5}], save=False)
        a = out["assessment"]
        self.assertEqual(a["method"], "checklist")
        self.assertEqual(a["rows"][0]["적정성"], "X")           # 비전 감지 = 부적정
        self.assertIn(a["rows"][0]["위험수준"], ("상", "중", "하"))
        self.assertIn("체크리스트법", out["html"])
        self.assertIn("고용노동부고시 제2024-76호", out["html"])  # 고시번호 표기(원문 문구는 미표기)

    # ── Dispatcher: 키 없으면 폴백(예외로 죽지 않음) ──
    def test_dispatcher_fallback_without_keys(self):
        # ★[2026-08-21] notify_cfg() 는 config/notify.yaml 을 **환경변수보다 먼저** 읽는다.
        #   현장에서 알림을 설정하면 이 테스트가 진짜 텔레그램을 쏘고 깨진다(실제로 발생).
        import agents.dispatcher as _d
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_URL"):
            os.environ.pop(k, None)
        with mock.patch.object(_d, "notify_cfg", return_value={"telegram_token": None, "telegram_chat": None, "webhook_url": None,
     "smtp_host": None, "smtp_port": 587, "smtp_user": None,
     "smtp_pass": None, "email_to": None}):
            r = self.agents["Dispatcher"].dispatch("high", "테스트")
        self.assertFalse(r["delivered"])      # 원격 전송 안 됨
        self.assertTrue(r["fallback"])        # 폴백(로그)으로 동작
        # log 채널은 항상 기록
        self.assertTrue(any(x["channel"] == "log" and x["sent"] for x in r["results"]))

    def test_dispatcher_critical_relay_is_supplementary(self):
        # §8: critical 의 safety_relay_signal 은 보조 신호(로그)일 뿐
        r = self.agents["Dispatcher"].dispatch("critical", "프레스 우회")
        relay = [x for x in r["results"] if x["channel"] == "safety_relay_signal"]
        self.assertTrue(relay)
        self.assertIn("보조", relay[0]["note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
