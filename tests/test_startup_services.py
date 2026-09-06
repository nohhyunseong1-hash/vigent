"""[CODE_REVIEW M7-3·M7-11] 기동 서비스 배선 — 서비스별 실패 격리 + 필수/선택 구분 + lifespan + 종료 정리.

M7-3 (main.py:450-482 였던 코드): try 1개에 서비스 5개가 들어 있어, 뒤쪽 하나가 예외면
  ① except 가 워커를 **콜드 모델로 즉시** 시작(B4 가 막은 경로 부활) ② 예외 지점 뒤 배선(alert_notify·retention)이 건너뛰어져
  "검출은 도는데 통보 없는" 상태가 WARNING 1줄로만 남았다.
계약:
  · 필수(readiness 예열·alert_queue·alert_notify) 실패 → M4-5 경로(_notify_startup_failure) 후 재raise = 기동 실패.
  · 선택(go2rtc·starvation_guard·retention_scheduler) 실패 → app_state.STARTUP_WARNINGS 에 기록, 나머지는 계속 기동.
  · 워커 즉시 시작(콜드) 폴백은 없다 — 워커는 예열 성공 콜백(on_ready)에서만 붙는다.
M7-11: on_event 대신 lifespan, 종료 시 alert_notify·alert_queue·retention_scheduler·starvation_guard 정리.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_notify  # noqa: E402
import alert_queue  # noqa: E402
import app_state  # noqa: E402
import main  # noqa: E402
import readiness  # noqa: E402
import retention_scheduler  # noqa: E402
import starvation_guard  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class _Disp:
    def channels_configured(self):
        return False

    def dispatch(self, *a, **k):
        return {}

    def _dispatch_now(self, *a, **k):
        return {}


def _bundle():
    class _Cfg:
        display_name = "t"

        def summary(self):
            return {"fallback_count": 0, "disabled_count": 0}
    return {"config": _Cfg(), "agents": {"Guard": object(), "Dispatcher": _Disp()}}


class StartupServices(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        app_state.STARTUP_WARNINGS.clear()
        ps = [
            mock.patch.object(main, "_load_theme", return_value=_bundle()),
            mock.patch.object(main, "_install_safety_nets"),
            mock.patch.object(main._cameras_router, "ensure_go2rtc", return_value=False),
            mock.patch.object(readiness, "start_background"),
            mock.patch.object(starvation_guard, "start"),
            mock.patch.object(alert_queue, "start"),
            mock.patch.object(alert_notify, "start"),
            mock.patch.object(retention_scheduler, "start"),
            mock.patch.object(main, "_notify_startup_failure"),
            mock.patch.object(main._cameras_router, "autostart_enabled", return_value=[]),
        ]
        self.m = {}
        for p in ps:
            self.m[p.attribute] = p.start()
            self.addCleanup(p.stop)

    def test_all_ok_wires_everything_and_no_warnings(self):
        main._startup()
        for name in ("start_background", "start"):
            pass
        self.m["start_background"].assert_called_once()
        alert_queue.start.assert_called_once()
        alert_notify.start.assert_called_once()
        retention_scheduler.start.assert_called_once()
        starvation_guard.start.assert_called_once()
        self.assertEqual(app_state.STARTUP_WARNINGS, [])
        self.m["_notify_startup_failure"].assert_not_called()

    def test_required_alert_queue_failure_is_startup_failure_without_cold_workers(self):
        alert_queue.start.side_effect = RuntimeError("db locked")
        with self.assertRaises(RuntimeError):
            main._startup()
        self.m["_notify_startup_failure"].assert_called_once()
        self.m["autostart_enabled"].assert_not_called()      # 콜드 워커 즉시 시작 폴백이 없어야 한다

    def test_optional_retention_failure_is_warning_and_rest_continues(self):
        retention_scheduler.start.side_effect = RuntimeError("disk")
        main._startup()
        self.assertEqual(len(app_state.STARTUP_WARNINGS), 1)
        self.assertIn("retention_scheduler", app_state.STARTUP_WARNINGS[0])
        alert_queue.start.assert_called_once()
        alert_notify.start.assert_called_once()
        self.m["_notify_startup_failure"].assert_not_called()

    def test_optional_starvation_failure_does_not_block_alert_wiring(self):
        starvation_guard.start.side_effect = RuntimeError("x")
        main._startup()
        self.assertTrue(any("starvation_guard" in w for w in app_state.STARTUP_WARNINGS))
        alert_notify.start.assert_called_once()
        retention_scheduler.start.assert_called_once()

    def test_health_exposes_startup_warnings(self):
        from fastapi.testclient import TestClient
        app_state.STARTUP_WARNINGS.append("startup:retention_scheduler: RuntimeError: disk")
        saved = main._API_TOKEN
        main._API_TOKEN = ""
        try:
            r = TestClient(main.app).get("/health").json()
        finally:
            main._API_TOKEN = saved
        self.assertIn("startup:retention_scheduler: RuntimeError: disk", r["warnings"])


class LifespanAndShutdown(unittest.TestCase):
    def test_app_uses_lifespan_not_on_event(self):
        self.assertEqual(main.app.router.on_startup, [])
        self.assertEqual(main.app.router.on_shutdown, [])
        self.assertIsNotNone(getattr(main.app.router, "lifespan_context", None))

    def test_shutdown_stops_background_services(self):
        with mock.patch.object(alert_notify, "stop") as an, mock.patch.object(alert_queue, "stop") as aq, \
                mock.patch.object(retention_scheduler, "stop") as rs, mock.patch.object(starvation_guard, "stop") as sg, \
                mock.patch.object(main._cameras_router, "stop_go2rtc"), \
                mock.patch("worker.manager") as mgr:
            mgr.stop_all.return_value = []
            main._shutdown()
        for m in (an, aq, rs, sg):
            m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
