"""[CODE_REVIEW M3-2·M3-3] 우회 경로(센서·브라우저 침입·brain·수동 relay)가 통보 게이트를 탄다.

배경: 이 네 경로는 dispatcher.dispatch 를 직접 불러 alert_gate(쿨다운·백오프·시간당 상한)를 건너뛰었다.
특히 /safety/sensor 는 임계 초과가 지속되면 센서 POST 주기마다 critical 통보+relay 가 나갔다.
계약(대표 지시):
  · 센서: POST 10회 연속 초과 → 통보 1(진입 전이)·기록 10 / 초과→정상→초과 → 통보 2(전이 2회)
  · 출처별 키(sensor:<종류>·browser_zone:<cam>·brain·manual)로 게이트 예산 분리
  · 브라우저 침입·수동 relay 는 반복 호출 시 게이트 쿨다운으로 1회만 통보
  · 응답 키 유지(alert_sent/phone_sent/alerted/delivered = 큐 적재 여부)
★통보 1건 = 전송기(dispatcher.dispatch) 호출 1회 = critical 이면 relay 1회(dispatcher 배선). 여기서는 전송기를
  대역으로 바꿔 호출 수를 센다(실제 채널·relay 미접촉).
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import alert_gate  # noqa: E402
import alert_notify  # noqa: E402
import main  # noqa: E402
from _isolate import isolate_alerts, isolate_data_dirs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class _Sender:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def __call__(self, level, message, meta):
        with self.lock:
            self.calls.append((level, message))
        return {"delivered": True, "results": [{"channel": "webhook", "sent": True}]}

    def wait(self, n, timeout=3.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if len(self.calls) >= n:
                    return len(self.calls)
            time.sleep(0.02)
        with self.lock:
            return len(self.calls)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        cls.addClassCleanup(isolate_alerts())
        cls.addClassCleanup(isolate_data_dirs())
        cls.client = TestClient(main.app)
        cls.client.__enter__()                       # startup(전송기 배선) — 아래서 대역으로 교체

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        main._API_TOKEN = cls._saved_token

    def setUp(self):
        from routers import safety_core as _sc
        _sc._SENSOR_DANGER.clear()                   # 센서 임계 상태(모듈 전역)를 테스트마다 초기화
        alert_gate.reset()
        alert_notify.stop()
        alert_notify.reset_for_test()
        self.sender = _Sender()
        alert_notify.set_sender(self.sender)
        alert_notify.start()
        self.logged: list[dict] = []
        import data_engine
        self._p = mock.patch.object(data_engine, "log_event",
                                    side_effect=lambda *a, **k: (self.logged.append(k) or {"evidence": None}))
        self._p.start()
        self.addCleanup(self._p.stop)

    def _settle(self, n):
        return self.sender.wait(n)


class SensorEdgeOnly(_Base):
    def _post(self, value):
        return self.client.post("/safety/sensor", json={"type": "co", "value": value, "site": "t-sensor"}).json()

    def test_sustained_exceed_notifies_once_records_each(self):
        rs = [self._post(50) for _ in range(10)]               # CO 50ppm ≥ 30 → 10회 연속 초과
        self.assertTrue(all(r["danger"] for r in rs))
        self.assertEqual([r["transition"] for r in rs], [True] + [False] * 9)
        self.assertEqual(rs[0]["alert_sent"], True)
        self.assertTrue(all(r["alert_sent"] is False for r in rs[1:]))
        self.assertEqual(len(self.logged), 10, "기록은 매 POST 남아야 한다")
        self.assertEqual(self._settle(1), 1, "통보(=relay)는 진입 전이 1회만")
        self.assertEqual(self.sender.calls[0][0], "critical")

    def test_reenter_after_recovery_is_new_transition(self):
        for _ in range(3):
            self._post(50)
        self._post(5)                                          # 정상 복귀
        for _ in range(3):
            self._post(50)                                     # 재초과 → 새 전이
        self.assertEqual(self._settle(2), 2, "초과→정상→초과 는 통보 2회(전이 2회)")
        self.assertEqual(len(self.logged), 6)

    def test_gate_key_is_per_source(self):
        """센서 통보가 영상 경보(cam 이름)의 게이트 예산을 쓰지 않는다."""
        self._post(50)
        self._settle(1)
        keys = list(alert_gate.snapshot().keys())
        self.assertIn("sensor:co/gas_alarm", keys)
        self.assertFalse(any(k.startswith("t-sensor/") for k in keys))


class BrowserZoneGated(_Base):
    def test_repeated_browser_intrusion_notifies_once(self):
        body = {"people": 1, "reasons": ["몸통 진입"], "zone": "위험구역A", "cam": "cam-b"}
        rs = [self.client.post("/zone/intrusion", json=body).json() for _ in range(3)]
        self.assertEqual([r["phone_sent"] for r in rs], [True, False, False])
        self.assertEqual(rs[1]["gate"], "cooldown")
        self.assertEqual(self._settle(1), 1)
        self.assertIn("browser_zone:cam-b/zone_intrusion", alert_gate.snapshot())
        self.assertEqual(len(self.logged), 3, "기록·증거는 억제하지 않는다")


class ManualRelayGated(_Base):
    def test_relay_endpoint_shape_and_gate(self):
        r1 = self.client.post("/dispatch/relay", json={"event": "guard_bypass"}).json()
        r2 = self.client.post("/dispatch/relay", json={"event": "guard_bypass"}).json()
        self.assertFalse(r1["is_primary_safety"])
        self.assertEqual(r1["relay"], "auxiliary_signal")
        self.assertTrue(r1["delivered"])                       # 큐 적재
        self.assertFalse(r2["delivered"])
        self.assertEqual(r2["gate"], "cooldown")
        self.assertEqual(self._settle(1), 1)
        self.assertEqual(self.sender.calls[0][0], "critical")


class AlertsTestIsIntentionalBypass(_Base):
    def test_alerts_test_skips_gate(self):
        """의도된 우회 — 게이트 상태를 만들지 않는다(문서화 계약)."""
        import agents.dispatcher as _d
        with mock.patch.object(_d.DispatcherAgent, "dispatch", return_value={"delivered": False}) as m:
            self.client.post("/alerts/test", json={"level": "high", "message": "시험"})
        self.assertEqual(m.call_count, 1)
        self.assertEqual(alert_gate.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
