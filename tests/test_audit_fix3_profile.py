"""CODE_AUDIT_20260928 #3 — 학원 전용 값이 공용 코드·판매용 포터블에 박히지 않는다. [2026-09-28]

★무엇을 고정하는가
  ① 설치 마법사에서 프로파일을 안 고르면 default(마스크 포함 3종)다. academy 는 명시했을 때만.
  ② deploy/portable/portable_overrides.yaml 에는 플랫폼 항목(detect.backend)만 있고 학원 결정(joints·fire_smoke)은
     deploy/academy/portable_overrides.academy.yaml 에 있다. 두 파일의 모든 from 은 원본에 정확히 1곳 존재한다(빌드가 요구하는 조건).
  ③ /health 제외 사유: 공용 기본 문구에 "학원" 이 없고, 프로파일 tuning 의 detect.exclusion_reasons 가 있으면 그것을 쓴다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "deploy"))

import setup_wizard as W  # noqa: E402
import worker  # noqa: E402


class WizardDefaultProfile(unittest.TestCase):
    def test_omitted_profile_is_default_with_mask(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td); (app / "config").mkdir(); (app / "data").mkdir()
            (app / "config" / "tuning.yaml").write_text("detect:\n  backend: torch\n", encoding="utf-8")
            import camera_registry
            import setup_console
            answers = {"device_name": "site-B-01", "cameras": [], "telegram_token": "123456789:AAEexampleTOKENexampleTOKENexample",
                       "telegram_chat": "-1001", "smtp_host": ""}
            with mock.patch.object(camera_registry, "_PUB", app / "data" / "cameras.json"), \
                 mock.patch.object(camera_registry, "_SEC", app / "data" / "camera_secrets.json"), \
                 mock.patch.object(setup_console, "_NOTIFY", app / "config" / "notify.yaml"), \
                 mock.patch.object(W, "lock_secret_file", lambda p: None):
                s = W.Wizard(answers, frame_grabber=lambda src: (True, "1280x720"), telegram_check=lambda: {"state": "ok", "bot": "b"},
                             smtp_check=lambda: {"state": "ok"}, app_root=app, out=lambda *_: None).run()
            self.assertEqual(s["profile"], "default")
            t = yaml.safe_load((app / "config" / "tuning.yaml").read_text(encoding="utf-8"))
            self.assertEqual(t["ppe"]["required"], ["NO-Hardhat", "NO-Safety-Vest", "NO-Mask"])
            self.assertIn("NO-Mask", json.dumps(W.PROFILES["default"]))


class OverridesSplit(unittest.TestCase):
    PORTABLE = _ROOT / "deploy/portable/portable_overrides.yaml"
    ACADEMY = _ROOT / "deploy/academy/portable_overrides.academy.yaml"
    SRC = {"tuning": _ROOT / "config/tuning.yaml", "vision": _ROOT / "themes/safety/vision.yaml"}

    def _load(self, p):
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    def test_portable_has_platform_only(self):
        o = self._load(self.PORTABLE)
        self.assertEqual(sorted(o), ["detect.backend"])
        body = "\n".join(str(v.get("why", "")) for v in o.values())
        self.assertNotIn("학원", body)

    def test_academy_holds_site_decisions(self):
        o = self._load(self.ACADEMY)
        self.assertEqual(sorted(o), ["detect.include_fire_smoke", "judgment.ergonomics.joints"])

    def test_every_from_matches_source_exactly_once(self):
        for f in (self.PORTABLE, self.ACADEMY):
            for k, v in self._load(f).items():
                src = self.SRC[v.get("file") or "tuning"].read_text(encoding="utf-8")
                self.assertEqual(src.count(v["from"]), 1, f"{f.name}:{k} from={v['from']!r}")

    def test_build_script_takes_profile(self):
        ps = (_ROOT / "scripts/build_portable.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('[string]$Profile', ps); self.assertIn("portable_overrides.\" + $Profile", ps)
        usb = (_ROOT / "scripts/deploy/build_usb.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("-Profile $Profile", usb)


class ExclusionReasonFromProfile(unittest.TestCase):
    def test_default_reason_is_site_neutral(self):
        self.assertNotIn("학원", worker.DETECTOR_EXCLUSION_REASONS["fire_smoke"])

    def test_profile_reason_overrides(self):
        def fake_val(sec, key, default, env=None):
            return 0 if (sec, key) == ("detect", "include_fire_smoke") else default
        with mock.patch.object(worker.tuning, "val", fake_val), \
             mock.patch.object(worker.tuning, "section", lambda name: {"exclusion_reasons": {"fire_smoke": "현장 사유 X"}} if name == "detect" else {}):
            d = worker.disabled_detectors()
        self.assertEqual(d["fire_smoke"], "현장 사유 X")
        self.assertIn("forklift", d)

    def test_academy_profile_declares_reason(self):
        t = yaml.safe_load((_ROOT / "deploy/academy/tuning.academy.yaml").read_text(encoding="utf-8"))
        self.assertIn("학원", t["detect"]["exclusion_reasons"]["fire_smoke"])


if __name__ == "__main__":
    unittest.main()
