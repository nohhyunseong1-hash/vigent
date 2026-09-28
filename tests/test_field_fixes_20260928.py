"""2026-09-28 실기 검증(field_verification_20260928 §2~§5)에서 나온 결함 7건의 수정을 고정한다.

  1) starvation_guard 기아 1단계 go2rtc DELETE 는 `src=`(실측: name= 은 200 이지만 삭제 안 됨)
  2) install_service.ps1 VIGENT_HOST 는 -Bind 를 따른다(0.0.0.0 고정이었음)
  3) install.ps1 업데이트 모드: 사용 중 사전 검사 + Move-Item 실패 시 서비스 복구
  4) acceptance_test A1: 한국어 Windows sc query 출력을 SCM 상태 코드로 읽고, 1순위는 Get-Service enum 이름
  5) 서비스 stderr 로그는 UTF-8(실측) — 절차서가 -Encoding UTF8 로 읽으라고 적는다
  6) 절차서: $pid 없음 · 등록은 PUT · 경과 초 수식 괄호
  7) _shutdown: 릴레이 미설정이면 "relay 미설정 … 건너뜀" 한 줄
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "deploy"))

import acceptance_test as AT  # noqa: E402
import relay  # noqa: E402
import starvation_guard as sg  # noqa: E402


def _ps(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8-sig")


def _parse_errors(rel: str) -> str:
    ps = shutil.which("powershell")
    if not ps:
        return "skip"
    f = _ROOT / rel
    cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('" + str(f).replace("'", "''")
           + "',[ref]$t,[ref]$e);Write-Output $e.Count")
    return subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60).stdout.strip()


class F1Go2rtcDelete(unittest.TestCase):
    def test_delete_uses_src_param(self):
        seen: list[tuple[str, str]] = []

        class _R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(sg.urllib.request, "urlopen", side_effect=lambda req, timeout=5: seen.append((req.full_url, req.get_method())) or _R()):
            self.assertTrue(sg._release_go2rtc_slot("cam 1"))
        self.assertEqual(seen, [("http://127.0.0.1:1984/api/streams?src=cam%201", "DELETE")])
        self.assertNotIn("name=", seen[0][0])


class F2BindEnv(unittest.TestCase):
    def test_vigent_host_follows_bind(self):
        s = _ps("deploy/windows/install_service.ps1")
        self.assertIn('"VIGENT_HOST=$Bind"', s); self.assertNotIn('"VIGENT_HOST=0.0.0.0"', s)
        self.assertEqual(_parse_errors("deploy/windows/install_service.ps1"), "0")


class F3UpdateMoveGuard(unittest.TestCase):
    def test_precheck_and_recovery(self):
        s = _ps("scripts/deploy/install.ps1")
        self.assertIn("$svcWasRunning", s); self.assertIn("Move-Item -LiteralPath $Target -Destination $Prev -Force -ErrorAction Stop", s)
        self.assertIn("Start-Service $svcName", s); self.assertIn("service_entry", s)     # 서비스 자신은 사용 중 목록에서 제외
        self.assertIn("현재 셸 위치가 설치 폴더 안이다", s)
        self.assertEqual(_parse_errors("scripts/deploy/install.ps1"), "0")


class F4ServiceState(unittest.TestCase):
    KO = "\nSERVICE_NAME: VIGENT\n        종류              : 10  WIN32_OWN_PROCESS\n        상태              : 4  RUNNING\n                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)\n"
    EN = "\nSERVICE_NAME: VIGENT\n        TYPE               : 10  WIN32_OWN_PROCESS\n        STATE              : 1  STOPPED\n"

    def test_parse_sc_state(self):
        self.assertEqual(AT.parse_sc_state(self.KO), "RUNNING"); self.assertEqual(AT.parse_sc_state(self.EN), "STOPPED")
        self.assertEqual(AT.parse_sc_state("        ??              : 4  ???????\n"), "RUNNING")     # 상태어까지 깨져도 코드로 읽는다
        self.assertEqual(AT.parse_sc_state("[SC] EnumQueryServicesStatus:OpenService FAILED 1060"), "없음/알 수 없음")

    def test_service_running_prefers_get_service(self):
        def run(cmd, **kw):
            if cmd[0] == "powershell":
                return mock.Mock(returncode=0, stdout="Running\n", stderr="")
            raise AssertionError("sc 로 떨어지면 안 된다")
        with mock.patch.object(AT.subprocess, "run", side_effect=run):
            self.assertEqual(AT._service_running("VIGENT"), (True, "RUNNING"))

        def run2(cmd, **kw):
            if cmd[0] == "powershell":
                return mock.Mock(returncode=1, stdout="", stderr="no service")
            return mock.Mock(returncode=0, stdout=self.KO, stderr="")
        with mock.patch.object(AT.subprocess, "run", side_effect=run2):
            self.assertEqual(AT._service_running("VIGENT"), (True, "RUNNING"))


class F5F6Procedure(unittest.TestCase):
    def test_doc_fixes(self):
        s = (_ROOT / "docs/deploy/field_verification_20260928.md").read_text(encoding="utf-8")
        self.assertNotRegex(s, r"^\s*\$pid\s*=", "PowerShell 자동 변수 $pid 에 대입하면 안 된다")
        self.assertIn('curl.exe -X PUT "http://127.0.0.1:1984/api/streams?name=t1&src=', s)
        self.assertNotIn("$((Get-Date) - $t0).TotalSeconds", s); self.assertIn("$(((Get-Date) - $t0).TotalSeconds)", s)
        self.assertIn("vigent.err.log -Tail 40 -Encoding UTF8", s)


class F7ShutdownRelayLog(unittest.TestCase):
    def test_disabled_relay_logs_one_line(self):
        import main
        with mock.patch.object(relay, "status", return_value={"enabled": False, "on": False, "off_failed": False}), \
             mock.patch.object(relay, "turn_off") as off, \
             mock.patch("worker.manager.stop_all", return_value="0"), mock.patch.object(main._cameras_router, "stop_go2rtc"), \
             mock.patch("alert_notify.stop"), mock.patch("alert_queue.stop"), mock.patch("retention_scheduler.stop"), mock.patch("starvation_guard.stop"), \
             mock.patch.object(main, "_log") as log:
            main._shutdown()
        off.assert_not_called()
        msgs = [str(c.args[0]) for c in log.info.call_args_list]
        self.assertTrue(any("relay 미설정" in m and "건너뜀" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()
