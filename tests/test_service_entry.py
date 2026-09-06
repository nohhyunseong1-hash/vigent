"""[5단계 5-2 정정] 서비스 런처(deploy/windows/service_entry.py) — import·인터프리터 단계 실패를 이벤트 로그(ID 1001)·startup_failure.json 에 남긴다.

실사고: VIGENT_REQUIRE_TOKEN=1 + .env 중화 → main.py 보안 게이트가 import 시점에 SystemExit(1) → [M4-5] 경로(_startup) 이전이라
흔적 0, NSSM Paused 반복. 계약: SystemExit 코드 그대로 반환·ImportError 는 2·성공이면 serve 호출·기록은 누적 count.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("service_entry", _ROOT / "deploy" / "windows" / "service_entry.py")
service_entry = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(service_entry)


class ServiceEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "data" / "startup_failure.json"
        self.events: list[str] = []
        self.writer = lambda msg: (self.events.append(msg) or True)

    def test_security_gate_system_exit_is_recorded_with_code(self):
        def importer():
            sys.stderr.write("[VIGENT 보안 오류] VIGENT_REQUIRE_TOKEN 설정됨 — 무인증 기동을 금지합니다.\n")
            raise SystemExit(1)
        code = service_entry.main_entry(["--port", "8010"], importer=importer, serve=lambda *a: None,
                                        state_path=self.state, event_writer=self.writer)
        self.assertEqual(code, 1)
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual((st["count"], st["stage"], st["event_id"]), (1, "import", 1001), "stage↔ID 대응: import=1001")
        self.assertIn("SystemExit(1)", st["last_error"])
        self.assertIn("VIGENT_REQUIRE_TOKEN", st["last_stderr"], "보안 게이트 안내문이 기록에 남아야 원인을 바로 안다")
        self.assertTrue(st["event_log_ok"])
        self.assertEqual(len(self.events), 1)
        self.assertIn("import 단계 기동 실패 1회", self.events[0])

    def test_import_error_returns_2_and_counts_accumulate(self):
        def importer():
            raise ImportError("No module named 'fastapi'")
        for n in (1, 2):
            code = service_entry.main_entry([], importer=importer, serve=lambda *a: None,
                                            state_path=self.state, event_writer=self.writer)
            self.assertEqual(code, 2)
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(st["count"], 2)
        self.assertIn("ImportError", st["last_error"])
        self.assertEqual(len(self.events), 2)

    def test_success_serves_app_with_args(self):
        class _M:
            app = object()
        served = {}

        def serve(app, host, port):
            served.update(app=app, host=host, port=port)
        code = service_entry.main_entry(["--host", "0.0.0.0", "--port", "8123"], importer=lambda: _M,
                                        serve=serve, state_path=self.state, event_writer=self.writer)
        self.assertEqual(code, 0)
        self.assertEqual((served["host"], served["port"]), ("0.0.0.0", 8123))
        self.assertIs(served["app"], _M.app)
        self.assertFalse(self.state.exists(), "성공 시 실패 기록을 남기지 않는다")
        self.assertEqual(self.events, [])

    def test_event_writer_failure_does_not_mask_exit_code(self):
        def bad_writer(msg):
            raise RuntimeError("eventcreate denied")
        code = service_entry.main_entry([], importer=lambda: (_ for _ in ()).throw(SystemExit(3)), serve=lambda *a: None,
                                        state_path=self.state, event_writer=bad_writer)
        self.assertEqual(code, 3)
        self.assertFalse(json.loads(self.state.read_text(encoding="utf-8"))["event_log_ok"])

    def test_install_script_registers_launcher_with_venv_only(self):
        t = (_ROOT / "deploy" / "windows" / "install_service.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("service_entry.py", t, "서비스 Application 은 런처를 거쳐야 한다(import 단계 실패 기록)")
        self.assertNotIn("Get-Command python", t, "시스템 python 폴백 금지 — .venv 없으면 명시적 오류로 중단")
        self.assertIn('".venv\\Scripts\\python.exe"', t)


if __name__ == "__main__":
    unittest.main()
