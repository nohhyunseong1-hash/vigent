"""[USB 1차, 승인 항목 5] 벤치 시작 전 GPU 오염 가드 — nvidia-smi 출력을 모의해 판정을 고정한다.

★왜: 2026-09-23 G-2 재확인·추론 분해 측정이 PUBG(TslGame.exe, GPU 67%·6.1GB) 실행 중에 이뤄져
  기동 67.9s(깨끗할 땐 10~14s)·ppe_fwd 23.8ms(깨끗할 땐 12.2ms) 로 오염됐다. 사람이 매번 기억할 수 없으니
  bench_4ch 가 시작 전에 막는다. Windows(WDDM)는 프로세스별 VRAM 이 [N/A] 라 **총 사용량**으로 판정한다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "bench"))

import bench_4ch as B  # noqa: E402

APPS_WDDM = (
    "19964, D:\\SteamLibrary\\steamapps\\common\\PUBG\\TslGame\\Binaries\\Win64\\TslGame.exe\n"
    "41256, C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\n"
    "41256, C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\n"   # 중복 → 한 번만
)


class ParseContention(unittest.TestCase):
    def test_parses_used_mb_and_process_names(self):
        used, names = B.parse_gpu_contention("6126\n", APPS_WDDM)
        self.assertEqual(used, 6126.0)
        self.assertEqual(names, ["TslGame.exe", "chrome.exe"])

    def test_tolerates_mib_suffix_and_blank(self):
        used, names = B.parse_gpu_contention("  512 MiB \n", "")
        self.assertEqual(used, 512.0)
        self.assertEqual(names, [])

    def test_garbage_is_zero_not_crash(self):
        used, names = B.parse_gpu_contention("[N/A]\n", "[Insufficient Permissions]\n")
        self.assertEqual(used, 0.0)
        self.assertEqual(names, [])


class AssertGpuFree(unittest.TestCase):
    def _run(self, mem: str, apps: str):
        def fake_run(cmd, **kw):
            out = mem if "--query-gpu=memory.used" in cmd else apps
            return mock.Mock(stdout=out)
        with mock.patch.object(B.subprocess, "run", side_effect=fake_run):
            return B.assert_gpu_free()

    def test_contended_gpu_aborts_with_names(self):
        with self.assertRaises(SystemExit) as cm:
            self._run("6126\n", APPS_WDDM)
        msg = str(cm.exception)
        self.assertIn("6126 MB", msg)
        self.assertIn("TslGame.exe", msg, "무엇이 GPU 를 쓰는지 프로세스명이 나와야 한다")

    def test_threshold_is_inclusive(self):
        with self.assertRaises(SystemExit):
            self._run("500\n", "")
        st = self._run("499\n", "")
        self.assertEqual(st["gpu_used_mb_before"], 499.0)

    def test_missing_nvidia_smi_aborts(self):
        with mock.patch.object(B.subprocess, "run", side_effect=FileNotFoundError("nvidia-smi")):
            with self.assertRaises(SystemExit) as cm:
                B.assert_gpu_free()
        self.assertIn("판정할 수 없다", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
