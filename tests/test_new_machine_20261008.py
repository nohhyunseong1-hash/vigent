"""2026-10-08 새 환경(GitHub 새 clone) 점검에서 나온 수정을 고정한다.

★무엇을 고정하는가
  ① guard.rfdetr_cache_dir: RF_HOME 미설정이면 저장소 weights 의 rf-detr-nano.pth 를 먼저 본다(없을 때만 ~/.roboflow/models).
     실측: 프로필 캐시가 지워지자 코드 변경 0 인데 게이트 ERROR 39(2026-10-08).
  ② setup_env.check_environment: 가짜 저장소 루트에서 없는 필수 가중치·캐시·비밀·데이터셋을 level 별로 보고하고, required 누락이면 1.
  ③ fetch_weights: `local:` 항목은 urlopen 으로 가지 않고 "어디서 복사·어떻게 확인" 메시지를 돌려준다.
  ④ 한글을 print 하는 진입 스크립트는 전부 stdout 을 UTF-8 로 재설정한다(cp949 콘솔에서 setup_env 가 첫 줄에서 죽던 것).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts"))

import fetch_weights as FW  # noqa: E402
import setup_env as SE  # noqa: E402
from agents import guard  # noqa: E402


class CacheDirFallback(unittest.TestCase):
    def test_rf_home_wins(self):
        with mock.patch.dict(os.environ, {"RF_HOME": "X:/custom"}):
            self.assertEqual(guard.GuardAgent.rfdetr_cache_dir(), Path("X:/custom"))

    def test_repo_weights_first_then_profile(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RF_HOME", None)
            repo = _ROOT / "vigent-core" / "weights"
            if (repo / "rf-detr-nano.pth").is_file():
                self.assertEqual(guard.GuardAgent.rfdetr_cache_dir(), repo)
            with mock.patch.object(Path, "is_file", return_value=False):
                self.assertEqual(guard.GuardAgent.rfdetr_cache_dir(), Path(os.path.expanduser("~/.roboflow/models")))


class Preflight(unittest.TestCase):
    def _fake_root(self, td: str, with_required: bool) -> Path:
        root = Path(td); (root / "scripts").mkdir(); (root / "vigent-core" / "weights").mkdir(parents=True); (root / "config").mkdir()
        (root / "scripts" / "fetch_weights.py").write_text((_ROOT / "scripts" / "fetch_weights.py").read_text(encoding="utf-8"), encoding="utf-8")
        (root / "vigent-core" / "data_paths.py").write_text((_ROOT / "vigent-core" / "data_paths.py").read_text(encoding="utf-8"), encoding="utf-8")
        man = {"weights": [
            {"file": "req.pth", "slot": "ppe", "required": True, "url": "release:t", "sha256": "a" * 64, "size_bytes": 3},
            {"file": "opt.pt", "slot": "ppe", "required": False, "url": "release:t", "sha256": "b" * 64, "size_bytes": 3},
            {"file": "loc.pth", "slot": "forklift", "required": False, "url": "local:runs/x.pth", "sha256": "c" * 64, "size_bytes": 3},
        ]}
        (root / "weights_manifest.json").write_text(json.dumps(man), encoding="utf-8")
        if with_required:
            (root / "vigent-core" / "weights" / "req.pth").write_bytes(b"abc")
            (root / "vigent-core" / "weights" / "rf-detr-nano.pth").write_bytes(b"x")
        return root

    def test_missing_required_reported(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RF_HOME", None)
            root = self._fake_root(td, with_required=False)
            items = SE.check_environment(root, home=root / "nohome")
            by = {i["name"]: i for i in items}
            self.assertFalse(by["req.pth"]["ok"]); self.assertEqual(by["req.pth"]["level"], "required"); self.assertIn("fetch_weights.py", by["req.pth"]["how"])
            self.assertIn("복사", by["loc.pth"]["how"]); self.assertIn("Release 미업로드", by["loc.pth"]["how"])
            self.assertFalse(by["config/notify.yaml"]["ok"]); self.assertIn("notify.example.yaml", by["config/notify.yaml"]["how"])
            self.assertEqual(SE.print_environment(items), 1)

    def test_all_required_present_is_ok(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RF_HOME", None)
            root = self._fake_root(td, with_required=True)
            items = SE.check_environment(root, home=root / "nohome")
            self.assertTrue(all(i["ok"] for i in items if i["level"] == "required"), [i["name"] for i in items if i["level"] == "required" and not i["ok"]])
            self.assertEqual(SE.print_environment(items), 0)


class LocalEntryMessage(unittest.TestCase):
    def test_local_url_is_manual_copy_not_urlopen(self):
        entry = {"file": "fk.pth", "url": "local:runs/finetune/x/ckpt.pth", "sha256": "d" * 64}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIGENT_WEIGHTS_BASE_URL", None)
            with mock.patch.object(FW.urllib.request, "urlopen", side_effect=AssertionError("urlopen 을 부르면 안 된다")):
                ok, msg = FW.download(entry, {"weights": []})
        self.assertFalse(ok); self.assertIn("복사", msg); self.assertIn("--check --all", msg); self.assertNotIn("unknown url type", msg)


class GateUsesVenvTools(unittest.TestCase):
    """gate.ps1 은 .venv 의 ruff·mypy 를 쓰고(전역 PATH 의존 금지) mypy 단계를 실제로 돈다. requirements-dev.txt 핀 = CI 핀."""

    def test_gate_script(self):
        s = (_ROOT / "scripts" / "gate.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("& $py -m ruff check vigent-core tests", s); self.assertIn("& $py -m mypy;", s); self.assertIn("& $py -m ruff @ruffArgs", s)
        self.assertNotRegex(s, r"(?m)^\s*ruff check", "전역 ruff 호출이 남아 있다")
        dev = (_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for pin in re.findall(r"^(ruff==[\d.]+|mypy==[\d.]+)", dev, re.M):
            self.assertIn(pin, ci, f"{pin} 이 CI 와 다르다")
        self.assertIn("requirements-dev.txt", (_ROOT / "scripts" / "setup_env.py").read_text(encoding="utf-8"))


class EntryScriptsUtf8(unittest.TestCase):
    NONASCII = re.compile(r"[\uAC00-\uD7A3\u2014\u2192\u2605\u2713\u2717]")

    def test_korean_printing_entry_scripts_reconfigure_stdout(self):
        bad = []
        for d in ("scripts", "scripts/deploy", "scripts/data", "scripts/eval", "scripts/train", "scripts/bench", "scripts/report"):
            for f in sorted((_ROOT / d).glob("*.py")):
                s = f.read_text(encoding="utf-8", errors="replace")
                if "__main__" in s and "print(" in s and self.NONASCII.search(s) and not re.search(r"reconfigure\(|PYTHONUTF8|PYTHONIOENCODING", s):
                    bad.append(str(f.relative_to(_ROOT)))
        self.assertEqual(bad, [], "cp949 콘솔에서 첫 print 에 죽는다 — stdout.reconfigure(encoding='utf-8') 추가")

    def test_setup_env_help_under_cp949(self):
        r = subprocess.run([sys.executable, str(_ROOT / "scripts" / "setup_env.py"), "--help"], capture_output=True,
                           env={**os.environ, "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-300:].decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
