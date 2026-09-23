"""[I-3] VRAM 상한 모사 훅(device.apply_cuda_mem_cap) — 벤치 전용, 미설정이면 무동작.

★왜 고정하나
  개발기(16GB)에서 잰 VRAM 을 파일럿기(8GB) 값으로 **추정하지 않기** 위해 torch 할당자에
  상한을 걸어 실제로 돌려 본다. 이 훅이 운영에서 조용히 켜지면 성능이 바뀌므로,
  "미설정 = 아무것도 안 함" 을 테스트로 못 박는다. 실제 CUDA 없이도 검증되게 torch 를 가짜로 끼운다.
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import device  # noqa: E402


def _fake_torch(total_bytes: int, calls: list):
    t = types.ModuleType("torch")
    cuda = types.SimpleNamespace()
    cuda.is_available = lambda: True
    cuda.get_device_properties = lambda i: types.SimpleNamespace(total_memory=total_bytes)
    cuda.set_per_process_memory_fraction = lambda frac, dev=0: calls.append((frac, dev))
    t.cuda = cuda
    t.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    return t


class CudaMemCap(unittest.TestCase):
    def setUp(self):
        device._cap_state.update(applied=False, cap_mb=None, total_mb=None, fraction=None, error=None)

    def test_unset_env_is_noop(self):
        calls: list = []
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(device._CAP_ENV, None)
            with mock.patch.dict(sys.modules, {"torch": _fake_torch(16 * 1024**3, calls)}):
                st = device.apply_cuda_mem_cap()
        self.assertFalse(st["applied"])
        self.assertEqual(calls, [], "미설정인데 상한을 걸었다 — 운영 동작이 바뀐다")

    def test_cap_sets_fraction_once(self):
        calls: list = []
        with mock.patch.dict(os.environ, {device._CAP_ENV: "8192"}):
            with mock.patch.dict(sys.modules, {"torch": _fake_torch(16 * 1024**3, calls)}):
                st1 = device.apply_cuda_mem_cap()
                st2 = device.apply_cuda_mem_cap()      # 두 번째는 걸지 않는다
        self.assertTrue(st1["applied"])
        self.assertAlmostEqual(st1["fraction"], 0.5, places=4)
        self.assertEqual(st1["cap_mb"], 8192.0)
        self.assertEqual(len(calls), 1, "상한은 한 번만 걸어야 한다")
        self.assertEqual(st2, st1)

    def test_failure_is_recorded_not_raised(self):
        t = types.ModuleType("torch")
        def _boom(i):
            raise RuntimeError("no cuda")
        t.cuda = types.SimpleNamespace(get_device_properties=_boom, set_per_process_memory_fraction=lambda *a: None)
        with mock.patch.dict(os.environ, {device._CAP_ENV: "8192"}):
            with mock.patch.dict(sys.modules, {"torch": t}):
                st = device.apply_cuda_mem_cap()
        self.assertFalse(st["applied"])
        self.assertIn("RuntimeError", st["error"] or "")

    def test_pick_device_cuda_applies_cap(self):
        calls: list = []
        with mock.patch.dict(os.environ, {device._CAP_ENV: "4096"}):
            os.environ.pop(device._ENV, None)
            with mock.patch.dict(sys.modules, {"torch": _fake_torch(16 * 1024**3, calls)}):
                dev = device.pick_device()
        self.assertEqual(dev, "cuda")
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][0], 0.25, places=4)


if __name__ == "__main__":
    unittest.main()
