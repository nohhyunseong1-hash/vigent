"""[5단계 마무리, 2026-09-06] go2rtc.exe 조달을 weights_manifest.json + scripts/fetch_weights.py 에 편입한 계약.

이전엔 "bin/go2rtc.exe 는 수동으로 받아 둔다"(SITE_CHECKLIST 수동 절차)였다. 이제 버전 고정 URL(v1.9.14 win64 zip) +
압축 해제본 sha256 검증으로 `fetch_weights.py --all` 이 받는다(실측 2026-09-06: 기존 파일을 치우고 받아 sha 일치·바이트 동일).
계약: root_dest=bin(weights/ 밖), archive_member=go2rtc.exe, sha256 64자·size, required=false(없으면 스냅샷 폴백),
fetch_weights.target_path 가 <repo>/bin/go2rtc.exe 를 만들고, bin/ 은 gitignore(바이너리 추적 금지).
"""
import importlib.util
import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


class Go2rtcManifest(unittest.TestCase):
    def setUp(self):
        man = json.loads((_ROOT / "weights_manifest.json").read_text(encoding="utf-8"))
        self.entry = next((w for w in man["weights"] if w["file"] == "go2rtc.exe"), None)
        self.assertIsNotNone(self.entry, "go2rtc.exe 항목이 매니페스트에 있어야 오프라인 조달이 된다")

    def test_entry_is_pinned_and_verifiable(self):
        e = self.entry
        self.assertRegex(e["url"], r"^https://github\.com/AlexxIT/go2rtc/releases/download/v[\d.]+/go2rtc_win64\.zip$", "버전 고정 URL")
        self.assertEqual(e["archive_member"], "go2rtc.exe")
        self.assertEqual(e["root_dest"], "bin")
        self.assertRegex(e["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(int(e["size_bytes"]), 10_000_000)
        self.assertFalse(e.get("required"), "없어도 스냅샷 폴백이 있으므로 기동 필수는 아니다(readiness 가 거부하면 안 됨)")

    def test_fetch_weights_targets_repo_bin(self):
        spec = importlib.util.spec_from_file_location("fetch_weights", _ROOT / "scripts" / "fetch_weights.py")
        fw = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(fw)
        self.assertEqual(fw.target_path(self.entry), _ROOT / "bin" / "go2rtc.exe")
        self.assertEqual(fw.target_path({"file": "x.pth"}), fw._WEIGHTS / "x.pth", "root_dest 없는 항목은 그대로 weights/")
        self.assertEqual(fw.target_path({"file": "y.onnx", "dest": "rtm_cache/hub/checkpoints"}),
                         fw._WEIGHTS / "rtm_cache" / "hub" / "checkpoints" / "y.onnx", "기존 dest 규칙 유지")

    def test_bin_is_gitignored(self):
        gi = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("bin/", [ln.strip() for ln in gi], "바이너리는 추적하지 않는다(매니페스트로 조달)")


if __name__ == "__main__":
    unittest.main()
