"""[5단계 5-2 4차 정정] deploy/windows/verify_service_reinstall.ps1 의 실사고 2건을 고정한다(2026-09-06 3차 실행).

① 헬퍼 매개변수 이름이 $Args 라 `@Args` 가 **빈 자동 변수**를 스플래팅 → nssm 이 인자 없이 실행(dump=사용법 배너, finally 의
   stop/set Start 무동작 → 서비스가 Paused/Automatic 으로 남음).
② 임시 .env 를 @("머리글", "VIGENT_API_TOKEN=" + $tok) 로 만들어 쉼표가 + 보다 먼저 묶임 → 토큰이 다음 줄로 떨어져 dotenv 가
   빈 토큰으로 읽음 → main.py 보안 게이트 SystemExit(1) → NSSM Paused.

정적 검사는 어디서나 돌고, PowerShell 이 있는 PC(개발 PC)에서는 스크립트에서 함수를 그대로 잘라내 실제로 실행해 확인한다
(CI 는 ubuntu 라 건너뜀). nssm 은 `@echo %*` 스텁 .cmd 로 대신한다 — 인자 없는 진짜 nssm 은 GUI 를 띄우고 멈춘다.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "deploy" / "windows" / "verify_service_reinstall.ps1"
_PS = shutil.which("powershell")


def _text() -> str:
    return _SCRIPT.read_bytes().decode("utf-8-sig")


def _function(name: str) -> str:
    """스크립트에서 `function <name>` 정의를 중괄호 깊이로 잘라낸다(문자열 안 중괄호는 이 함수들에 없다)."""
    lines = _text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("function " + name + " ") or ln.startswith("function " + name + "("))
    depth = 0
    for j in range(start, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth == 0:
            return "\n".join(lines[start:j + 1])
    raise AssertionError("함수 끝을 찾지 못함: " + name)


def _run_ps(body: str, timeout: int = 60) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.ps1"
        p.write_bytes(b"\xef\xbb\xbf" + ("[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$ErrorActionPreference = 'Stop'\n" + body).encode("utf-8"))
        r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                           capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


class VerifyScriptStatic(unittest.TestCase):
    def test_encoding_bom_crlf(self):
        b = _SCRIPT.read_bytes()
        self.assertTrue(b.startswith(b"\xef\xbb\xbf"), "PowerShell 5.1 이 한글을 바로 읽으려면 UTF-8 BOM")
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), "CRLF 통일")

    def test_no_args_named_parameter(self):
        t = _text()
        self.assertNotIn("param([string[]]$Args)", t, "$Args 매개변수 + @Args 는 빈 자동 변수를 스플래팅한다(3차 실사고)")
        self.assertIn("param([string[]]$Argv)", t)
        self.assertIn("@nssmPath @Argv".replace("@nssmPath", "$nssmPath"), t)

    def test_temp_env_and_self_check(self):
        t = _text()
        self.assertIn("function Build-TempEnvLines(", t)
        self.assertNotIn('"VIGENT_API_TOKEN=" + $tmpToken)', t, "배열 리터럴 안 문자열 결합(우선순위 사고) 금지")
        self.assertIn('-match "^VIGENT_API_TOKEN=[a-z0-9]{32}$"', t, "쓴 파일을 다시 읽어 토큰 줄 1개를 확인(규칙 11)")

    def test_finally_restores_backed_up_service_state(self):
        t = _text()
        self.assertIn("function Restore-ServiceState()", t)
        self.assertIn('$nssmStart0 = (Nssm @("get", $ServiceName, "Start")).Trim()', t, "Start 타입은 백업값으로 되돌린다")
        self.assertNotIn('Nssm @("set", $ServiceName, "Start", "SERVICE_DISABLED")', t, "하드코딩 DISABLED 금지")
        self.assertIn("$svcRestoreOk = Restore-ServiceState", t)
        self.assertIn("if (-not $svcRestoreOk) { $restoreOk = $false }", t, "서비스 원복 실패는 파일 원복 실패와 같은 등급")

    def test_diag_on_failure_paths(self):
        t = _text()
        self.assertIn("function Show-Diag(", t)
        self.assertIn('Show-Diag "예외"', t, "install 실패(throw) 등 모든 예외에서 err 꼬리·startup_failure.json 즉시 출력")
        self.assertIn('Show-Diag "Running 아님"', t)
        self.assertIn('-Filter "vigent.err-*.log"', t, "NSSM 은 시작마다 err 로그를 회전 — 실패 stderr 는 회전본에 남는다")

    def test_nssm_env_passed_as_separate_args_and_no_bogus_confirm(self):
        t = _text()
        self.assertIn('Nssm (@("set", $ServiceName, "AppEnvironmentExtra") + $envArr)', t)
        self.assertIn('Nssm (@("set", $ServiceName, "AppEnvironmentExtra") + $badEnv)', t)
        self.assertNotIn('"restart", $ServiceName, "confirm"', t, "nssm restart/stop 은 confirm 인자를 받지 않는다")
        self.assertNotIn('"stop", $ServiceName, "confirm"', t)


@unittest.skipIf(_PS is None, "PowerShell 없음(CI ubuntu) — 개발 PC 에서만 실행")
class VerifyScriptBehaviour(unittest.TestCase):
    def test_nssm_helper_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "nssm_stub.cmd"
            stub.write_text("@echo %*\r\n", encoding="ascii")
            body = ('$nssmPath = "' + str(stub) + '"\n' + _function("Nssm") + "\n"
                    'Write-Output ("OUT1=" + (Nssm @("get", "VIGENT", "Start")))\n'
                    'try { Nssm @() | Out-Null; Write-Output "EMPTY=no-throw" } catch { Write-Output "EMPTY=threw" }\n')
            out = _run_ps(body)
        self.assertIn("OUT1=get VIGENT Start", out, out)
        self.assertIn("EMPTY=threw", out, "인자 없는 nssm 호출은 거부(GUI 멈춤 방지)")

    def test_temp_env_lines_keep_token_on_one_line(self):
        try:
            from dotenv import dotenv_values
        except ImportError:  # pragma: no cover
            self.skipTest("python-dotenv 없음")
        body = (_function("New-TempToken") + "\n" + _function("Build-TempEnvLines") + "\n"
                '$tok = New-TempToken\n'
                '(Build-TempEnvLines $tok @("ROBOFLOW_API_KEY", "VIGENT_API_TOKEN", "TELEGRAM_BOT_TOKEN") "X") | ForEach-Object { Write-Output $_ }\n')
        out = _run_ps(body)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 4, out)
        self.assertRegex(lines[1], r"^VIGENT_API_TOKEN=[a-z0-9]{32}$", "토큰은 반드시 같은 줄")
        self.assertEqual(lines[2:], ["ROBOFLOW_API_KEY=", "TELEGRAM_BOT_TOKEN="], "원본 키는 값만 비우고 토큰 키는 중복 금지")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
            v = dotenv_values(p)
        self.assertEqual(len(v.get("VIGENT_API_TOKEN") or ""), 32, "dotenv 가 실제로 32자 토큰을 읽어야 보안 게이트를 지난다")
        self.assertEqual(v.get("ROBOFLOW_API_KEY"), "")


if __name__ == "__main__":
    unittest.main()
