"""CODE_AUDIT_20260928 #5 — 설치 스크립트 고정값·인자 전달. [2026-09-28]

★무엇을 고정하는가
  ① install.ps1 은 install_service.ps1 을 같은 세션에서 직접 호출한다(-File 로 배열 인자를 풀어 넘기지 않는다)·외부 바인드면 토큰 검사·설치 결과 파일을 남긴다.
  ② 설치.bat 은 %TEMP%\\vigent_install_result.env 에서 TARGET/PORT 를 읽고, 인수시험에 --base 를 넘긴다. C:\\VIGENT 는 폴백일 뿐이다.
  ③ acceptance_test.default_base() 는 app/data/install_result.json 의 port 를 쓴다(없으면 8010).
  ④ 배치·ps1 실행 파일은 전부 CRLF 다(LF 가 하나라도 있으면 실패).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "deploy"))

import acceptance_test as AT  # noqa: E402


def _ps(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8-sig")


class InstallScript(unittest.TestCase):
    def test_service_script_called_directly_with_array(self):
        s = _ps("scripts/deploy/install.ps1")
        self.assertIn("& $isv -Root $App -PythonExe $Py -Bind $Bind -Port $Port -ExtraEnv $extra", s)
        code_lines = [ln for ln in s.splitlines() if not ln.lstrip().startswith("#")]   # 주석(예전 형태 설명)은 제외
        self.assertFalse([ln for ln in code_lines if "-File $isv" in ln], "install_service.ps1 을 -File 로 띄우면 배열 인자가 풀린다")

    def test_external_bind_requires_token(self):
        s = _ps("scripts/deploy/install.ps1")
        self.assertIn('VIGENT_API_TOKEN=\\S{16,}', s); self.assertIn('외부 바인드($Bind)에는 VIGENT_API_TOKEN 이 필수', s)

    def test_install_result_written(self):
        s = _ps("scripts/deploy/install.ps1")
        self.assertIn('"install_result.json"', s); self.assertIn("vigent_install_result.env", s)
        for key in ("TARGET=$Target", "PORT=$Port", "BIND=$Bind"):
            self.assertIn(key, s)


class BatchReadsResult(unittest.TestCase):
    def test_bat_reads_target_and_port(self):
        b = (_ROOT / "deploy/usb/설치.bat").read_text(encoding="utf-8")
        self.assertIn("vigent_install_result.env", b); self.assertIn('set "TARGET=%RES_TARGET%"', b); self.assertIn("--base http://127.0.0.1:%PORT%", b)
        self.assertIn('set "TARGET=C:\\VIGENT"', b, "폴백 기본값은 남긴다")


class AcceptanceBase(unittest.TestCase):
    def test_default_base_from_result_file(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td); (app / "data").mkdir()
            self.assertEqual(AT.default_base(app), "http://127.0.0.1:8010")
            (app / "data" / "install_result.json").write_text(json.dumps({"port": 8020, "target": "D:\\V"}), encoding="utf-8")
            self.assertEqual(AT.default_base(app), "http://127.0.0.1:8020")
            (app / "data" / "install_result.json").write_text("{broken", encoding="utf-8")
            self.assertEqual(AT.default_base(app), "http://127.0.0.1:8010")


class CrlfExecutables(unittest.TestCase):
    FILES = [*(_ROOT / "deploy/usb").glob("*.bat"), *(_ROOT / "deploy/portable").glob("*.bat"), *(_ROOT / "deploy/windows").glob("*.ps1"),
             *(_ROOT / "scripts/deploy").glob("*.ps1"), _ROOT / "scripts/build_portable.ps1"]

    def test_all_crlf(self):
        self.assertTrue(self.FILES)
        for f in self.FILES:
            raw = f.read_bytes()
            self.assertNotRegex(raw.decode("utf-8", "replace"), re.compile(r"(?<!\r)\n"), f"{f.name}: LF 줄바꿈 발견")

    def test_build_usb_verifies_crlf(self):
        self.assertIn("CRLF 검증", _ps("scripts/deploy/build_usb.ps1"))

    def test_ps1_real_bom_not_literal(self):
        """★2026-09-28 실제 사고: fix #3(75b6285) 패치가 build_portable.ps1 첫머리에 BOM 을 **글자 그대로** '\\xef\\xbb\\xbf' 로 써
        PowerShell 이 파일을 전혀 파싱하지 못했다(28 parse errors). BOM 은 바이트 EF BB BF 여야 하고, 텍스트 '\\x' 로 시작하면 안 된다."""
        for f in self.FILES:
            if f.suffix != ".ps1":
                continue
            raw = f.read_bytes()
            self.assertFalse(raw.startswith(b"\\x"), f"{f.name}: BOM 이 글자('\\x..')로 들어갔다")
            self.assertTrue(raw.startswith(bytes([0xEF, 0xBB, 0xBF])), f"{f.name}: UTF-8 BOM 없음(PS 5.1 은 한글을 ANSI 로 읽는다)")

    def test_ps1_parses(self):
        """PowerShell 파서로 배포 .ps1 전부를 검사한다(문법 오류 0). powershell 이 없는 기계(CI Linux)는 skip."""
        import shutil
        import subprocess
        ps = shutil.which("powershell")
        if not ps:
            self.skipTest("powershell 없음")
        for f in self.FILES:
            if f.suffix != ".ps1":
                continue
            cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('" + str(f).replace("'", "''")
                   + "',[ref]$t,[ref]$e);Write-Output $e.Count")
            r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.stdout.strip(), "0", f"{f.name}: PowerShell 파서 오류 {r.stdout.strip()!r} {r.stderr[-200:]}")


if __name__ == "__main__":
    unittest.main()
