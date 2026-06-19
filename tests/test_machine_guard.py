"""5단계 검증 — guard_bypass(프레스/전단기) + /dispatch/relay 보조 방호신호(§8)"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import vision_loader  # noqa: E402
from agents import build_agents  # noqa: E402


class TestMachineGuard(unittest.TestCase):
    def setUp(self):
        cfg = vision_loader.load_vision("safety")
        self.agents = build_agents(cfg)

    def test_guard_bypass_is_critical(self):
        # 손이 기계 방호구역에 진입 → guard_bypass(critical)
        r = self.agents["Analyst"].judge({"hand_in_machine_zone": True})
        self.assertEqual(r["level"], "critical")
        self.assertTrue(any(f["rule"] == "guard_bypass" for f in r["fired"]))

    def test_relay_is_supplementary_not_primary(self):
        # §8: 보조 방호신호이며 1차 안전기능이 아님을 명시
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_URL"):
            os.environ.pop(k, None)
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
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
