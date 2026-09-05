"""5단계 검증 — guard_bypass(프레스/전단기) + /dispatch/relay 보조 방호신호(§8)"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import vision_loader  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402
from agents import build_agents  # noqa: E402


class TestMachineGuard(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())     # [4단계 ④] relay()→dispatch()→큐 기록을 운영 DB 밖으로
        cfg = vision_loader.load_vision("safety")
        self.agents = build_agents(cfg)

    def test_guard_bypass_is_critical(self):
        # 손이 기계 방호구역에 진입 → guard_bypass(critical)
        r = self.agents["Analyst"].judge({"hand_in_machine_zone": True})
        self.assertEqual(r["level"], "critical")
        self.assertTrue(any(f["rule"] == "guard_bypass" for f in r["fired"]))

    def test_relay_is_supplementary_not_primary(self):
        # §8: 보조 방호신호이며 1차 안전기능이 아님을 명시
        # ★[2026-08-21] 환경변수만 지우면 부족하다 — notify_cfg() 는 config/notify.yaml 을
        #   **먼저** 읽으므로, 현장에서 알림을 설정하면 이 테스트가 실제 텔레그램을 전송하고
        #   delivered=True 가 되어 깨진다(실제로 발생). 설정을 통째로 격리한다.
        import agents.dispatcher as _d
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_URL"):
            os.environ.pop(k, None)
        with mock.patch.object(_d, "notify_cfg", return_value={"telegram_token": None, "telegram_chat": None, "webhook_url": None,
     "smtp_host": None, "smtp_port": 587, "smtp_user": None,
     "smtp_pass": None, "email_to": None}):
            r = self.agents["Dispatcher"].relay("guard_bypass")
        self.assertFalse(r["is_primary_safety"])         # 1차 안전기능 아님
        self.assertEqual(r["relay"], "auxiliary_signal")
        self.assertIn("§8", r["boundary"])
        # 키 없으면 원격 전송은 폴백(그래도 예외 없이 동작)
        self.assertFalse(r["delivered"])

    def test_vision_yaml_has_machine_zone(self):
        cfg = vision_loader.load_vision("safety")
        zones = (cfg.raw.get("judgment", {}) or {}).get("zones", {})
        self.assertIn("machine_hazard_zones", zones)


class TestMachineEndpoints(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "vigent-core"))
        import main  # noqa
        from fastapi.testclient import TestClient
        self.main = main
        # ★[2026-08-20] 인증 격리 — 배포 .env 의 VIGENT_API_TOKEN 이 있으면 이 엔드포인트
        #   테스트가 전부 401 로 깨진다(현장 노트북에서 실제 발생). 인증 자체는
        #   test_security_gate.py 등이 따로 검증한다. 상세는 test_endpoints_smoke.py 주석.
        self._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        self.addCleanup(isolate_alerts())     # [4단계 ④] startup 배선(전송기·재시도 스레드) 격리
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.main._API_TOKEN = self._saved_token

    def test_machine_zone_roundtrip(self):
        c = self.client
        before = c.get("/zone/machine").json()
        try:
            tri = {"points": [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4}, {"x": 0.5, "y": 0.6}]}
            self.assertTrue(c.post("/zone/machine", json=tri).json()["ok"])
            self.assertEqual(len(c.get("/zone/machine").json()["points"]), 3)
        finally:
            c.post("/zone/machine", json=before)  # 원복

    def test_dispatch_relay_endpoint(self):
        r = self.client.post("/dispatch/relay", json={"event": "guard_bypass"}).json()
        self.assertFalse(r["is_primary_safety"])
        self.assertEqual(r["relay"], "auxiliary_signal")


class TestGuardBypassText(unittest.TestCase):
    """[2026-08-21] §8 보조 방호신호 문구가 현장별로 바뀌는지.

    배경: 문구가 "프레스/전단기 위험구역 신체 진입 감지" 로 **코드에 하드코딩**돼 있어,
    지게차 실습장 같은 다른 현장에서 폰에 프레스 경보가 떠 담당자가 혼란스럽고
    시연 설득력도 떨어졌다(학원 준비 중 발견).
    """

    def _agent(self):
        import agents.dispatcher as _d
        from agents.dispatcher import DispatcherAgent

        class _Cfg:
            raw = {"dispatch": {"on_severity": {"critical": ["log"]}}}
        return _d, DispatcherAgent(_Cfg())

    def _empty_cfg(self):
        return {"telegram_token": None, "telegram_chat": None, "webhook_url": None,
                "smtp_host": None, "smtp_port": 587, "smtp_user": None,
                "smtp_pass": None, "email_to": None}

    def test_default_text_is_site_neutral(self):
        """★기본 문구에 특정 설비명(프레스·전단기)이 들어가면 안 된다."""
        _d, a = self._agent()
        with mock.patch.object(_d, "notify_cfg", return_value=self._empty_cfg()):
            r = a.relay("guard_bypass")
        text = [x for x in r["alert"]["results"] if x["channel"] == "log"][0]["text"]
        self.assertIn("위험기계", text)
        self.assertNotIn("프레스", text, "기본 문구에 현장 특정 설비명이 남아 있다")
        self.assertNotIn("전단기", text)

    def test_text_is_configurable_per_site(self):
        """현장 문구를 tuning.yaml(alerts.guard_bypass_text)로 바꿀 수 있다."""
        _d, a = self._agent()
        vals = {"guard_bypass_text": "중장비 방호구역 신체 진입 감지"}
        with mock.patch.object(_d, "notify_cfg", return_value=self._empty_cfg()),              mock.patch.object(_d.tuning, "val",
                               side_effect=lambda s, k, d, env=None: vals.get(k, d)):
            r = a.relay("guard_bypass")
        text = [x for x in r["alert"]["results"] if x["channel"] == "log"][0]["text"]
        self.assertIn("중장비 방호구역", text)

    def test_safety_boundary_unchanged(self):
        """★문구를 바꿔도 §8 경계(1차 안전기능 아님) 표기는 그대로여야 한다."""
        _d, a = self._agent()
        with mock.patch.object(_d, "notify_cfg", return_value=self._empty_cfg()):
            r = a.relay("guard_bypass")
        self.assertFalse(r["is_primary_safety"])
        self.assertIn("§8.1", r["boundary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
