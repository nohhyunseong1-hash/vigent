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
    """결함 3 + 회귀(결함 8): 사용 중 검사는 서비스 소유 프로세스 트리를 제외하고, 서비스 중지 **전에** 외부 점유·셸 위치를 본다."""

    def test_precheck_and_recovery(self):
        s = _ps("scripts/deploy/install.ps1")
        self.assertIn("$svcWasRunning", s); self.assertIn("Move-Item -LiteralPath $Target -Destination $Prev -Force -ErrorAction Stop", s)
        self.assertIn("Start-Service $svcName", s); self.assertIn("function Get-ExternalBusyProcesses", s)
        self.assertIn("현재 셸 위치가 설치 폴더 안이다", s)
        # 순서: 검사(Get-ExternalBusyProcesses 호출) → Stop-Service → Move-Item
        i_chk = s.index("$chk = Get-ExternalBusyProcesses"); i_stop = s.index("Stop-Service $svcName -Force"); i_mv = s.index("Move-Item -LiteralPath $Target")
        self.assertLess(i_chk, i_stop); self.assertLess(i_stop, i_mv)
        self.assertEqual(_parse_errors("scripts/deploy/install.ps1"), "0")

    @staticmethod
    def _run_busy(target: str, procs: list[dict], svc_pid: int, cwd: str) -> dict:
        """install.ps1 안의 Get-ExternalBusyProcesses 함수 본문을 그대로 꺼내 가짜 프로세스 목록으로 실행한다(코드 = 시험 대상)."""
        import json
        import re
        import tempfile
        ps = shutil.which("powershell")
        if not ps:
            raise unittest.SkipTest("powershell 없음")
        src = _ps("scripts/deploy/install.ps1")
        m = re.search(r"function Get-ExternalBusyProcesses.*?\n}\n", src, re.S)
        assert m, "함수를 찾지 못했다"
        procs_ps = ",".join("[pscustomobject]@{ProcessId=%d;ParentProcessId=%d;ExecutablePath='%s';Name='%s';CommandLine='%s'}"
                            % (p["pid"], p["ppid"], p["exe"], p["name"], p.get("cmd", "")) for p in procs)
        script = (m.group(0) + "\n$r = Get-ExternalBusyProcesses -Target '%s' -Procs @(%s) -ServicePid %d -Cwd '%s'\n"
                  "@{cwd_inside=[bool]$r.cwd_inside; busy=@($r.busy | ForEach-Object { $_.ProcessId }); owned=$r.owned_count} | ConvertTo-Json -Compress\n"
                  % (target, procs_ps, svc_pid, cwd))
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "busy.ps1"; f.write_bytes(b"\xef\xbb\xbf" + script.replace("\n", "\r\n").encode("utf-8"))
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(f)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-400:]
        out = json.loads(r.stdout.strip())
        out["busy"] = [int(x) for x in ([out["busy"]] if isinstance(out["busy"], int) else (out["busy"] or []))]
        return out

    SERVICE_TREE = [  # nssm(서비스 PID) → service_entry python → go2rtc : 전부 <Target> 안의 exe
        {"pid": 100, "ppid": 4, "exe": r"D:\VIGENT_TEST\app\deploy\windows\nssm.exe", "name": "nssm.exe"},
        {"pid": 102, "ppid": 100, "exe": r"D:\VIGENT_TEST\python\python.exe", "name": "python.exe", "cmd": "python service_entry.py --host 127.0.0.1"},
        {"pid": 103, "ppid": 102, "exe": r"D:\VIGENT_TEST\app\bin\go2rtc.exe", "name": "go2rtc.exe"},
        {"pid": 200, "ppid": 1, "exe": r"C:\Windows\explorer.exe", "name": "explorer.exe"},
    ]

    def test_service_running_is_not_busy(self):
        """서비스 Running 상태에서 업데이트 설치가 막히면 안 된다(회귀 재현: 예전엔 nssm·go2rtc 가 busy 로 잡혔다)."""
        r = self._run_busy(r"D:\VIGENT_TEST", self.SERVICE_TREE, 100, r"C:\Users\x")
        self.assertEqual(r["busy"], []); self.assertFalse(r["cwd_inside"]); self.assertEqual(r["owned"], 3)

    def test_external_shell_inside_target_is_reported_before_stop(self):
        """외부 셸이 설치 폴더 안에 있거나 외부 exe 가 폴더 안 파일이면 busy — install.ps1 은 이때 Stop-Service 전에 Fail 한다."""
        procs = self.SERVICE_TREE + [{"pid": 300, "ppid": 1, "exe": r"D:\VIGENT_TEST\app\vigent-core\tool.exe", "name": "tool.exe"}]
        r = self._run_busy(r"D:\VIGENT_TEST", procs, 100, r"D:\VIGENT_TEST\app")
        self.assertTrue(r["cwd_inside"]); self.assertEqual(r["busy"], [300])
        r2 = self._run_busy(r"D:\VIGENT_TEST", self.SERVICE_TREE, 0, r"C:\Users\x")     # 서비스가 없는데 그 exe 들이 돌면(고아) busy 가 맞다
        self.assertEqual(sorted(r2["busy"]), [100, 102, 103]); self.assertEqual(r2["owned"], 0)


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
