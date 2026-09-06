"""[CODE_REVIEW M7-2·M7-2b] 개발 런처(run.ps1)와 서비스(install_service.ps1)의 환경 정합 + rtmlib 포즈 캐시 조달.

M7-2: run.ps1 이 VIGENT_CAPTURE_MODE·PYTHONUTF8·RF_HOME·TORCH_HOME 을 **미설정 시에만** 서비스와 같은 값으로 채운다.
      (정적 검사 — PowerShell 실행 없이 텍스트로 확인. 파일은 UTF-8 BOM + CRLF 여야 한다: PS 5.1 한글 주석 구문 오류 방지.)
M7-2b: weights_manifest.json 에 rtmlib 2파일이 required 로 있고, dest 가 TORCH_HOME/hub/checkpoints 와 일치하며,
      fetch_weights.target_path 가 그 경로를 만든다. 압축 항목은 archive_member 로 1개만 꺼낸다(zip 실제 해제는 임시 zip 로 검증).
"""
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import fetch_weights as fw  # noqa: E402

_RUN = _ROOT / "run.ps1"
_SVC = _ROOT / "deploy" / "windows" / "install_service.ps1"


def _run_text() -> str:
    return _RUN.read_bytes().decode("utf-8-sig")


class RunPs1Parity(unittest.TestCase):
    def test_bom_and_crlf(self):
        b = _RUN.read_bytes()
        self.assertTrue(b.startswith(b"\xef\xbb\xbf"), "run.ps1 은 UTF-8 BOM 이어야 한다(PS 5.1 한글)")
        self.assertIn(b"\r\n", b)
        self.assertNotIn(b"\n\n\n\n", b)

    def test_sets_four_service_env_only_when_unset(self):
        t = _run_text()
        want = {
            "VIGENT_CAPTURE_MODE": r'"thread"',
            "PYTHONUTF8": r'"1"',
            "RF_HOME": r'Join-Path \$Dir "vigent-core\\weights"',
            "TORCH_HOME": r'Join-Path \$Dir "vigent-core\\weights\\rtm_cache"',
        }
        for name, val in want.items():
            pat = re.compile(r'if \(-not \$env:' + name + r'\) \{ \$env:' + name + r' = ' + val + r' \}')
            self.assertTrue(pat.search(t), f"run.ps1 에 미설정-시 기본값이 없다: {name}")

    def test_python_311_only_no_bare_python_candidate(self):
        """[M7-5·M7-6] 런처는 .venv(3.11) → py -3.11 만 시도한다. bare python/py 후보는 없고, 후보 검사가 3.11 을 확인한다."""
        t = _run_text()
        self.assertIn('@("py", "-3.11")', t)
        self.assertNotIn('@("python", "")', t, "PATH 의 bare python 후보가 남아 있다(py 기본 3.14 PC 에서 미검증 인터프리터)")
        self.assertIn("sys.version_info[:2] == (3, 11)", t)
        self.assertIn("Python 3.11(정본)", t)                     # 없으면 안내 후 종료
        self.assertIn("exit 1", t)

    def test_values_match_install_service(self):
        svc = _SVC.read_bytes().decode("utf-8-sig")
        self.assertIn('"VIGENT_CAPTURE_MODE=thread"', svc)
        self.assertIn('"PYTHONUTF8=1"', svc)
        self.assertIn('$WeightsDir = Join-Path $Core "weights"', svc)
        self.assertIn('$RtmCacheDir = Join-Path $WeightsDir "rtm_cache"', svc)
        self.assertIn('"RF_HOME=$WeightsDir"', svc)
        self.assertIn('"TORCH_HOME=$RtmCacheDir"', svc)


class RtmlibProcurement(unittest.TestCase):
    def setUp(self):
        self.man = json.loads((_ROOT / "weights_manifest.json").read_text(encoding="utf-8"))
        self.rtm = [w for w in self.man["weights"] if w.get("backend") == "rtmlib"]

    def test_manifest_has_two_required_rtmlib_files_under_torch_home_checkpoints(self):
        names = sorted(w["file"] for w in self.rtm)
        self.assertEqual(names, ["rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx",
                                 "yolox_m_8xb8-300e_humanart-c2c7a14a.onnx"])
        for w in self.rtm:
            self.assertTrue(w.get("required"), w["file"])
            self.assertEqual(w.get("dest"), "rtm_cache/hub/checkpoints")   # rtmlib: TORCH_HOME/hub/checkpoints
            self.assertEqual(w.get("archive_member"), "end2end.onnx")
            self.assertTrue(w["url"].endswith(".zip"))
            self.assertEqual(len(w["sha256"]), 64)
            self.assertEqual(fw.target_path(w), fw._WEIGHTS / "rtm_cache" / "hub" / "checkpoints" / w["file"])

    def test_readiness_required_check_honors_dest(self):
        """readiness.required_weights_missing 은 매니페스트 dest 하위 경로를 봐야 한다(안 보면 예열이 '없음'으로 기동 거부)."""
        sys.path.insert(0, str(_ROOT / "vigent-core"))
        import readiness
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wdir = root / "vigent-core" / "weights"
            (wdir / "rtm_cache" / "hub" / "checkpoints").mkdir(parents=True)
            (wdir / "rtm_cache" / "hub" / "checkpoints" / "a.onnx").write_bytes(b"x")
            (wdir / "b.pth").write_bytes(b"x")
            man = {"weights": [
                {"file": "a.onnx", "dest": "rtm_cache/hub/checkpoints", "required": True},
                {"file": "b.pth", "required": True},
                {"file": "c.onnx", "dest": "rtm_cache/hub/checkpoints", "required": True},
            ]}
            (root / "weights_manifest.json").write_text(json.dumps(man), encoding="utf-8")
            with mock.patch.object(readiness, "_ROOT", root):
                self.assertEqual(readiness.required_weights_missing(), ["c.onnx"])

    def test_download_extracts_single_member_and_verifies(self):
        payload = b"onnx-bytes-for-test"
        import hashlib
        entry = {"file": "m.onnx", "url": "https://example.invalid/m.zip", "archive_member": "end2end.onnx",
                 "dest": "rtm_cache/hub/checkpoints", "sha256": hashlib.sha256(payload).hexdigest(),
                 "size_bytes": len(payload), "required": True}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("m/end2end.onnx", payload)
            z.writestr("m/deploy.json", "{}")
        data = buf.getvalue()

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(fw, "_WEIGHTS", Path(td)), \
                mock.patch.object(fw.urllib.request, "urlopen", return_value=_Resp(data)):
            ok, msg = fw.download(entry, self.man)
            self.assertTrue(ok, msg)
            out = Path(td) / "rtm_cache" / "hub" / "checkpoints" / "m.onnx"
            self.assertEqual(out.read_bytes(), payload)
            self.assertEqual(fw.verify(entry)[0], fw.OK)
            self.assertEqual(sorted(p.name for p in out.parent.iterdir()), ["m.onnx"], "임시·압축 파일이 남으면 안 된다")


if __name__ == "__main__":
    unittest.main()
