"""[USB 1차 계획 1] USB 루트 레이아웃 계약(scripts/deploy/usb_layout.py) — 빌드와 테스트가 같은 것을 본다.

★왜: build_usb.ps1 이 만드는 것과 설치기가 기대하는 것이 어긋나면 현장에서야 드러난다.
  계약을 파이썬 한 곳에 두고, 여기서는 임시 트리로 통과/미달/경고를 고정한다. 실제 4.7GB 포터블은 만들지 않는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "deploy"))

import usb_layout as L  # noqa: E402


def make_tree(root: Path, *, backend: str = "torch", with_optional: bool = True) -> None:
    """계약을 만족하는 최소 트리(내용은 더미)."""
    files = {
        "VERSION.txt": "태그 v-test\n",
        "설치.bat": "@echo off\n",
        "installer/preflight.ps1": "# preflight\n",
        "portable/VIGENT_시작.bat": "@echo off\n",
        "portable/vc_redist.x64.exe": "MZ",
        "portable/python/python.exe": "MZ",
        "portable/python/wheels_cuda/torch-2.12.0+cu130-cp311-cp311-win_amd64.whl": "PK",
        "portable/app/vigent-core/main.py": "app = None\n",
        "portable/app/vigent-core/weights/ppe_rfdetr_v1.pth": "weights",
        "portable/app/config/tuning.yaml": f"detect:\n  backend: {backend}\n",
        "driver/README.txt": "드라이버 자리\n",
    }
    if with_optional:
        files["installer/install.ps1"] = "# install\n"
        files["installer/uninstall.ps1"] = "# uninstall\n"
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    L.manifest(root, tag="v-test", commit="abc1234")


class UsbLayoutContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_complete_tree_passes(self):
        make_tree(self.root)
        fails, warns = L.verify(self.root)
        self.assertEqual(fails, [])
        self.assertEqual(warns, [])
        m = json.loads((self.root / "usb_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["tag"], "v-test")
        self.assertIn("portable/app/vigent-core/main.py", m["sha256"])

    def test_each_required_item_missing_is_a_fail(self):
        """필수 항목 하나씩 빼면 그 항목이 [미달] 로 나와야 한다 — 목록이 빈 계약이 되지 않게."""
        for rel in L.REQUIRED:
            if rel == "usb_manifest.json":
                continue
            with self.subTest(rel=rel):
                make_tree(self.root)
                target = self.root / rel.rstrip("/")
                if rel.endswith("/"):
                    import shutil
                    shutil.rmtree(target)
                else:
                    target.unlink()
                fails, _ = L.verify(self.root)
                self.assertTrue(any(rel in f for f in fails), f"{rel} 누락이 미달로 안 잡혔다: {fails}")

    def test_optional_missing_is_only_a_warning(self):
        make_tree(self.root, with_optional=False)
        fails, warns = L.verify(self.root)
        self.assertEqual(fails, [])
        self.assertEqual(len(warns), 2)

    def test_git_dir_in_portable_is_forbidden(self):
        make_tree(self.root)
        (self.root / "portable/app/.git").mkdir()
        fails, _ = L.verify(self.root)
        self.assertTrue(any(".git" in f for f in fails))

    def test_secrets_in_portable_are_forbidden(self):
        make_tree(self.root)
        (self.root / "portable/app/config/notify.yaml").write_text("telegram_token: x\n", encoding="utf-8")
        fails, _ = L.verify(self.root)
        self.assertTrue(any("notify.yaml" in f for f in fails), "비밀이 USB 에 실리면 미달이어야 한다")

    def test_cpu_backend_is_rejected_for_gpu_usb(self):
        make_tree(self.root, backend="onnx-cpu")
        fails, _ = L.verify(self.root)
        self.assertTrue(any("torch" in f for f in fails))

    def test_missing_cuda_wheel_is_rejected(self):
        make_tree(self.root)
        for w in (self.root / "portable/python/wheels_cuda").glob("*.whl"):
            w.unlink()
        fails, _ = L.verify(self.root)
        self.assertTrue(any("wheels_cuda" in f for f in fails))

    def test_sha_mismatch_is_detected(self):
        make_tree(self.root)
        (self.root / "portable/app/vigent-core/main.py").write_text("app = 'tampered'\n", encoding="utf-8")
        fails, _ = L.verify(self.root)
        self.assertTrue(any("SHA256" in f for f in fails))


if __name__ == "__main__":
    unittest.main()
