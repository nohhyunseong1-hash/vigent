"""CODE_AUDIT_20260928 B-6 — pip check 화이트리스트. [2026-09-28]

★무엇을 고정하는가
  ① classify(): headless 로 충족되는 cv2 이름 불일치 6건만 허용, 버전 충돌·다른 패키지 누락은 '그 밖'.
  ② main(): pip check 를 mock 으로 고정해 허용만 있으면 0, 그 밖이 있으면 1, headless 가 없으면 1.
  ③ 개발기(실제 venv): 실행 결과가 0 이다(허용 목록 밖 문제 없음) — pip 가 없거나 느린 CI 환경은 skip 하지 않고 그대로 검사한다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import check_pip_deps as C  # noqa: E402

SIX = [
    "albucore 0.0.24 requires opencv-python-headless, which is not installed.",
    "albumentations 2.0.8 requires opencv-python-headless, which is not installed.",
    "rtmlib 0.0.15 requires opencv-contrib-python, which is not installed.",
    "rtmlib 0.0.15 requires opencv-python, which is not installed.",
    "supervision 0.29.0.post0 requires opencv-python, which is not installed.",
    "trackers 2.4.0 requires opencv-python, which is not installed.",
]


class Classify(unittest.TestCase):
    def test_six_allowed_only(self):
        ok, bad = C.classify(SIX + ["", "No broken requirements found."])
        self.assertEqual(len(ok), 6); self.assertEqual(bad, [])

    def test_other_problems_are_bad(self):
        extra = ["torch 2.12.0+cu130 has requirement setuptools<82, but you have setuptools 83.0.0.",
                 "rfdetr 1.8.0 requires transformers, which is not installed.",
                 "albumentations 2.0.8 requires opencv-python-headless>=4.9, which is not installed.",   # 버전 조건이 붙은 변형은 허용하지 않는다
                 "evilpkg 1.0 requires opencv-python, which is not installed."]                        # 허용 패키지가 아니다
        ok, bad = C.classify(SIX + extra)
        self.assertEqual(len(ok), 6); self.assertEqual(bad, extra)


class Main(unittest.TestCase):
    def _run(self, out: str, headless: bool = True) -> int:
        with mock.patch.object(C, "run_pip_check", return_value=(1 if out.strip() else 0, out)), \
             mock.patch.object(C, "headless_installed", return_value=headless), mock.patch.object(sys, "argv", ["x"]):
            return C.main()

    def test_exit_codes(self):
        self.assertEqual(self._run("\n".join(SIX)), 0)
        self.assertEqual(self._run("\n".join(SIX) + "\nfoo 1.0 requires bar, which is not installed."), 1)
        self.assertEqual(self._run("\n".join(SIX), headless=False), 1)
        self.assertEqual(self._run("No broken requirements found.\n"), 0)

    def test_real_environment(self):
        import subprocess
        r = subprocess.run([sys.executable, str(_ROOT / "scripts" / "check_pip_deps.py")], capture_output=True, encoding="utf-8", errors="replace",
                           timeout=180)      # text=True 는 cp949 콘솔에서 UTF-8 출력을 못 읽어 stdout 이 None 이 된다
        self.assertEqual(r.returncode, 0, (r.stdout or "")[-600:] + (r.stderr or "")[-300:])


if __name__ == "__main__":
    unittest.main()
