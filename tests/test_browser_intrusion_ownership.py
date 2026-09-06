"""[CODE_REVIEW M8-1·M3-8] /zone/intrusion — cam 필수, 워커가 감시 중인 카메라면 기록만(통보는 워커 위임).

실사고 경로: /safety 시연 화면이 getUserMedia 를 가로채 go2rtc 카메라를 넣으면 브라우저가 **같은 카메라**를 다시 판정하고
browser_zone:<cam> 키로 통보 → 워커(cam=<카메라명>)와 게이트 키가 달라 **둘 다** 통보됐다(M3-8 이중 통보).
계약(대표 승인 2026-09-06):
  · cam 없으면 400.
  · 워커가 감시 중인 카메라: 기록만(증거 1장, source=browser) — 통보 없음(phone_sent=False, gate="worker_owned").
  · 워커가 감시하지 않는 카메라(시연·로컬 웹캠): 기존대로 브라우저 통보 허용(게이트 통과).
  · 같은 카메라 브라우저+워커 → 통보 1(워커) · 증거 1(브라우저 기록).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import alert_gate  # noqa: E402
import alert_notify  # noqa: E402
import data_engine  # noqa: E402
import main  # noqa: E402
import worker  # noqa: E402
from _isolate import isolate_alerts, isolate_data_dirs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from routers import zone as zone_router  # noqa: E402


class _FakeDispatcher:
    def channels_configured(self):
        return True


def _status(running: dict[str, bool]) -> dict:
    return {"cameras": {cid: {"running": r, "name": cid} for cid, r in running.items()}}


class BrowserIntrusionOwnership(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.addCleanup(isolate_data_dirs())
        self._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        self.addCleanup(setattr, main, "_API_TOKEN", self._saved_token)
        p = mock.patch.dict(zone_router.STATE, {zone_router.DEFAULT_THEME: {"agents": {"Dispatcher": _FakeDispatcher()}}})
        p.start()
        self.addCleanup(p.stop)
        alert_gate.reset_for_test() if hasattr(alert_gate, "reset_for_test") else None
        self.client = TestClient(main.app)
        self.body = {"people": 1, "reasons": ["몸통 진입"], "zone": "위험구역A", "source": "browser"}

    def test_cam_required(self):
        r = self.client.post("/zone/intrusion", json=self.body)
        self.assertEqual(r.status_code, 400, r.text)

    def test_worker_owned_camera_records_only_and_delegates(self):
        with mock.patch.object(worker.manager, "status", return_value=_status({"cam-w": True})):
            r = self.client.post("/zone/intrusion", json={**self.body, "cam": "cam-w", "image_base64": "AAAA"}).json()
        self.assertFalse(r["phone_sent"])
        self.assertEqual(r["gate"], "worker_owned")
        self.assertTrue(r.get("delegated_to_worker"))
        ev = data_engine.list_events(limit=5)
        self.assertEqual(len(ev), 1, "기록은 1건 남는다")
        self.assertEqual(ev[0].get("source"), "browser")
        self.assertTrue(ev[0].get("evidence"), "증거 1장")
        self.assertNotIn("browser_zone:cam-w/zone_intrusion", alert_gate.snapshot(), "브라우저 통보 키가 게이트에 생기면 안 된다")

    def test_same_camera_browser_plus_worker_notifies_once_records_once(self):
        with mock.patch.object(worker.manager, "status", return_value=_status({"cam-w": True})):
            self.client.post("/zone/intrusion", json={**self.body, "cam": "cam-w", "image_base64": "AAAA"})
            n = alert_notify.submit(cam="cam-w", rule="zone_intrusion", level="high", message="[cam-w] 침입", meta={})
        self.assertTrue(n["queued"], "워커 통보 1")
        self.assertEqual(alert_notify.stats()["queue_depth"], 1, "통보 대기열에 워커 건 1개만")
        self.assertEqual(len(data_engine.list_events(limit=5)), 1, "증거(브라우저 기록) 1")

    def test_unowned_camera_browser_notifies_through_gate(self):
        with mock.patch.object(worker.manager, "status", return_value=_status({"cam-w": True})):
            r1 = self.client.post("/zone/intrusion", json={**self.body, "cam": "webcam-demo"}).json()
            r2 = self.client.post("/zone/intrusion", json={**self.body, "cam": "webcam-demo"}).json()
        self.assertTrue(r1["phone_sent"])
        self.assertFalse(r2["phone_sent"])
        self.assertEqual(r2["gate"], "cooldown")
        self.assertIn("browser_zone:webcam-demo/zone_intrusion", alert_gate.snapshot())

    def test_fixed_go2rtc_stream_matched_by_source(self):
        """페이지가 config/go2rtc.yaml 고정 스트림('tapo')을 쓰면 그 RTSP 소스가 실행 중 워커의 소스와 같을 때 워커 소유로 본다."""
        import camera_registry as _reg
        with mock.patch.object(worker.manager, "status", return_value=_status({"cam1": True})), \
                mock.patch.object(zone_router, "_go2rtc_fixed_source", return_value="rtsp://u:p@10.0.0.9/stream1"), \
                mock.patch.object(_reg, "source_of", return_value="rtsp://u:p@10.0.0.9/stream1"):
            r = self.client.post("/zone/intrusion", json={**self.body, "cam": "tapo"}).json()
        self.assertEqual(r["gate"], "worker_owned")
        self.assertFalse(r["phone_sent"])

    def test_pages_expose_cam_id_and_core_sends_it(self):
        for name in ("index.html", "index_local.html"):
            t = (_ROOT / "themes" / "safety" / name).read_text(encoding="utf-8")
            self.assertEqual(t.count("window.VIGENT_CAM_ID ="), 1, name)
        js = (_ROOT / "vigent-core" / "static" / "realtime_core.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(js.count("window.VIGENT_CAM_ID"), 1)
        self.assertEqual(js.count("cam:camId"), 1)

    def test_stopped_worker_camera_counts_as_unowned(self):
        with mock.patch.object(worker.manager, "status", return_value=_status({"cam-w": False})):
            r = self.client.post("/zone/intrusion", json={**self.body, "cam": "cam-w"}).json()
        self.assertTrue(r["phone_sent"])


if __name__ == "__main__":
    unittest.main()
