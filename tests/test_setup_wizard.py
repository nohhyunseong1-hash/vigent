"""[USB 1차 계획 3] 첫 실행 마법사(scripts/deploy/setup_wizard.py) — 실제 카메라·망 없이 검증한다.

★검증기는 순수 함수, 마법사는 프레임 수신·getMe·SMTP 를 주입받는다. 여기서는 전부 가짜를 넣고
  **파일이 실제로 생겼는지·비밀이 공개 파일에 새지 않았는지·검증 실패가 중단으로 이어지는지** 를 고정한다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "deploy"))
sys.path.insert(0, str(_REPO / "vigent-core"))

import setup_wizard as W  # noqa: E402

ANSWERS = {
    "device_name": "site-A-01", "profile": "academy",
    "cameras": [{"id": "cam1", "name": "입구", "source": "rtsp://admin:S3cret!@192.168.77.11:554/stream1"}],
    "telegram_token": "123456789:AAEexampleTOKENexampleTOKENexample", "telegram_chat": "-1001234567890",
    "smtp_host": "", "required_ppe": "NO-Hardhat, NO-Safety-Vest",
}


class Validators(unittest.TestCase):
    def test_device_name(self):
        self.assertIsNone(W.check_device_name("site-A-01"))
        self.assertIsNotNone(W.check_device_name("현장1"))
        self.assertIsNotNone(W.check_device_name("-bad"))

    def test_rtsp(self):
        self.assertIsNone(W.check_rtsp("rtsp://u:p@10.0.0.5:554/live"))
        self.assertIsNone(W.check_rtsp("rtsp://10.0.0.5/live"))
        self.assertIsNotNone(W.check_rtsp("http://10.0.0.5/live"))
        self.assertIsNotNone(W.check_rtsp("rtsp://"))

    def test_chat_id(self):
        self.assertIsNone(W.check_chat_id("-1001234567890"))
        self.assertIsNotNone(W.check_chat_id("abc"))


class RequiredPpeWrite(unittest.TestCase):
    def test_append_when_ppe_block_is_commented(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tuning.yaml"
            p.write_text("detect:\n  backend: torch\n# ppe:\n#   required: [NO-Hardhat, NO-Safety-Vest, NO-Mask]\n", encoding="utf-8")
            how = W.write_required_ppe(p, ["NO-Hardhat"])
            import yaml
            self.assertEqual(how, "appended")
            self.assertEqual(yaml.safe_load(p.read_text(encoding="utf-8"))["ppe"]["required"], ["NO-Hardhat"])

    def test_replace_when_ppe_block_is_active(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tuning.yaml"
            p.write_text("ppe:\n  required: [NO-Mask]\n  other: 1\ndetect:\n  backend: torch\n", encoding="utf-8")
            how = W.write_required_ppe(p, ["NO-Hardhat", "NO-Safety-Vest"])
            import yaml
            self.assertEqual(how, "replaced")
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            self.assertEqual(data["ppe"]["required"], ["NO-Hardhat", "NO-Safety-Vest"])
            self.assertEqual(data["ppe"]["other"], 1, "같은 블록의 다른 키를 건드리면 안 된다")


class WizardRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name)
        (self.app / "config").mkdir(); (self.app / "data").mkdir()
        (self.app / "config" / "tuning.yaml").write_text("detect:\n  backend: torch\n", encoding="utf-8")
        import camera_registry
        import setup_console
        self.patches = [
            mock.patch.object(camera_registry, "_PUB", self.app / "data" / "cameras.json"),
            mock.patch.object(camera_registry, "_SEC", self.app / "data" / "camera_secrets.json"),
            mock.patch.object(setup_console, "_NOTIFY", self.app / "config" / "notify.yaml"),
            mock.patch.object(W, "lock_secret_file", lambda p: None),        # icacls 는 여기서 안 돌린다
        ]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        self.log: list[str] = []

    def _wizard(self, answers, grab=None, tg=None):
        return W.Wizard(answers, frame_grabber=grab or (lambda src: (True, "1280x720")),
                        telegram_check=tg or (lambda: {"state": "ok", "bot": "VGT97_bot"}),
                        smtp_check=lambda: {"state": "ok"}, app_root=self.app, out=self.log.append)

    def test_full_run_creates_files_and_masks_secrets(self):
        s = self._wizard(dict(ANSWERS)).run()
        self.assertEqual(s["device_name"], "site-A-01")
        self.assertEqual([c["id"] for c in s["cameras"]], ["cam1"])
        pub = json.loads((self.app / "data" / "cameras.json").read_text(encoding="utf-8"))
        sec = json.loads((self.app / "data" / "camera_secrets.json").read_text(encoding="utf-8"))
        self.assertTrue(pub["cameras"][0]["enabled"], "서비스가 자동복원하려면 enabled 여야 한다")
        self.assertNotIn("S3cret!", json.dumps(pub), "공개 레지스트리에 비밀번호가 새면 안 된다")
        self.assertIn("S3cret!", sec["cam1"])
        import yaml
        n = yaml.safe_load((self.app / "config" / "notify.yaml").read_text(encoding="utf-8"))
        self.assertEqual(n["telegram_chat"], "-1001234567890")
        self.assertTrue(n["telegram_token"].startswith("123456789:"))
        t = yaml.safe_load((self.app / "config" / "tuning.yaml").read_text(encoding="utf-8"))
        self.assertEqual(t["ppe"]["required"], ["NO-Hardhat", "NO-Safety-Vest"])
        self.assertTrue((self.app / "data" / "site_setup.json").is_file())
        self.assertTrue(any("이메일 채널 없음" in w for w in s["warnings"]), "이메일 건너뛰면 경고가 남아야 한다")
        self.assertFalse(any("S3cret!" in ln for ln in self.log), "화면 출력에 비밀번호가 나오면 안 된다")

    def test_bad_frame_aborts_non_interactive(self):
        with self.assertRaises(SystemExit) as cm:
            self._wizard(dict(ANSWERS), grab=lambda src: (False, "열기 실패")).run()
        self.assertIn("프레임 수신 실패", str(cm.exception))
        self.assertFalse((self.app / "data" / "cameras.json").exists(), "실패한 카메라는 등록되면 안 된다")

    def test_bad_rtsp_format_aborts(self):
        a = dict(ANSWERS); a["cameras"] = [{"id": "cam1", "name": "x", "source": "http://1.2.3.4/x"}]
        with self.assertRaises(SystemExit):
            self._wizard(a).run()

    def test_telegram_failure_aborts(self):
        with self.assertRaises(SystemExit) as cm:
            self._wizard(dict(ANSWERS), tg=lambda: {"state": "config_error", "reason": "getMe HTTP 401"}).run()
        self.assertIn("getMe", str(cm.exception))

    def test_unknown_profile_aborts(self):
        a = dict(ANSWERS); a["profile"] = "factory"
        with self.assertRaises(SystemExit):
            self._wizard(a).run()

    def test_bad_ppe_class_aborts(self):
        a = dict(ANSWERS); a["required_ppe"] = "NO-Hardhat, Gloves"
        with self.assertRaises(SystemExit) as cm:
            self._wizard(a).run()
        self.assertIn("Gloves", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
