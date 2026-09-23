"""[USB 1차, 승인 항목 5 — 2026-09-23 개정] 벤치 시작 전 GPU 오염 가드: VIGENT 외 **단일 프로세스** VRAM ≥ 500MB 면 중단.

★왜 프로세스별인가: 합계 기준(구판)은 이 개발기의 유휴 VRAM(브라우저·Discord·Claude 앱 합 1.5GB)만으로 항상 막혔다.
★왜 Windows 성능 카운터인가: WDDM 에서 nvidia-smi 의 프로세스별 used_memory 는 [N/A] 다(실측). 'GPU Process Memory\\Dedicated Usage' 가 준다.
★제외: dwm.exe·explorer.exe(사용자 지정). VIGENT 자신의 서버 PID 도 뺀다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "bench"))

import bench_4ch as B  # noqa: E402

# Get-Counter 를 'pid,name,mb' 로 찍은 실제 모양(2026-09-23 개발기): dwm 12.4GB · NVIDIA Overlay 4.0GB · msw 964MB · Discord 411MB
COUNTER = (
    "2108,dwm.exe,12412.0\n"
    "5464,NVIDIA Overlay.exe,4029.0\n"
    "38004,msw.exe,964.0\n"
    "21844,Discord.exe,411.0\n"
    "11364,explorer.exe,166.0\n"
    "21844,Discord.exe,20.0\n"          # 같은 pid 두 번(luid/phys) → 합산 431
    "9999,(exited),3.0\n"
    "garbage line\n"
)


class Parse(unittest.TestCase):
    def test_parse_sums_per_pid_and_skips_garbage(self):
        procs = {pid: (n, mb) for pid, n, mb in B.parse_gpu_procs(COUNTER)}
        self.assertEqual(procs[21844], ("Discord.exe", 431.0))
        self.assertEqual(procs[5464], ("NVIDIA Overlay.exe", 4029.0))
        self.assertNotIn(0, procs)
        self.assertEqual(len(procs), 6)


class Violations(unittest.TestCase):
    def setUp(self):
        self.procs = B.parse_gpu_procs(COUNTER)

    def test_excludes_dwm_and_explorer_but_catches_others(self):
        bad = B.gpu_violations(self.procs)
        names = [n for _, n, _ in bad]
        self.assertNotIn("dwm.exe", names)
        self.assertNotIn("explorer.exe", names)
        self.assertEqual(names, ["NVIDIA Overlay.exe", "msw.exe"], "임계 이상이고 제외 목록에 없는 것만, 큰 순서")

    def test_threshold_is_inclusive_and_sum_matters(self):
        self.assertEqual([n for _, n, _ in B.gpu_violations(self.procs, threshold_mb=431.0)][-1], "Discord.exe")
        self.assertNotIn("Discord.exe", [n for _, n, _ in B.gpu_violations(self.procs, threshold_mb=431.1)])

    def test_own_vigent_pid_is_ignored(self):
        procs = self.procs + [(777, "python.exe", 2500.0)]
        self.assertIn("python.exe", [n for _, n, _ in B.gpu_violations(procs)])
        self.assertNotIn("python.exe", [n for _, n, _ in B.gpu_violations(procs, own_pids={777})])

    def test_exclude_list_is_the_user_specified_one(self):
        self.assertEqual(B.GPU_EXCLUDE, {"dwm.exe", "explorer.exe"})


class AssertGpuFree(unittest.TestCase):
    def _run(self, text: str):
        with mock.patch.object(B.subprocess, "run", return_value=mock.Mock(stdout=text, stderr="")), \
                mock.patch.object(B, "_vigent_pids", return_value=set()):
            return B.assert_gpu_free()

    def test_contended_aborts_naming_offenders(self):
        with self.assertRaises(SystemExit) as cm:
            self._run(COUNTER)
        msg = str(cm.exception)
        self.assertIn("NVIDIA Overlay.exe", msg); self.assertIn("4029 MB", msg); self.assertIn("msw.exe", msg)
        self.assertNotIn("dwm.exe", msg)

    def test_clean_desktop_passes(self):
        st = self._run("2108,dwm.exe,12412.0\n11364,explorer.exe,166.0\n21844,Discord.exe,411.0\n")
        self.assertEqual(st["gpu_threshold_mb"], 500.0)
        self.assertTrue(any(s.startswith("Discord.exe") for s in st["gpu_procs_before"]))

    def test_empty_counter_aborts(self):
        with self.assertRaises(SystemExit) as cm:
            self._run("")
        self.assertIn("판정할 수 없다", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
