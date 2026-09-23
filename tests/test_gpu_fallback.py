"""[USB 1차 항목 4 — 확정] GPU 빌드에서 CUDA 를 못 쓰면 조용히 CPU 로 떨어지지 않는다.

계약(device.py · routers/system.py · index_hub.html 이 같이 본다):
  VIGENT_EXPECT_GPU=1 + cuda 불가 → device._note_device 가 CRITICAL 1회 + gpu_fallback_status()["fallback"]=True
  기대 없음(env 미설정)                 → 아무 로그도, fallback 도 없다(기본 동작 무변경)
  /health.gpu 에 expected_gpu / fallback / fallback_reason 키가 항상 있다
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


def _torch(cuda: bool):
    t = types.ModuleType("torch")
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda,
                                   get_device_properties=lambda i: types.SimpleNamespace(total_memory=8 * 1024**3),
                                   set_per_process_memory_fraction=lambda *a: None)
    t.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    return t


class GpuFallback(unittest.TestCase):
    def setUp(self):
        device._gpu_state.update(expected_gpu=False, fallback=False, fallback_reason=None, device=None)
        device._cap_state.update(applied=False, cap_mb=None, total_mb=None, fraction=None, error=None)

    def test_expected_gpu_without_cuda_is_loud(self):
        with mock.patch.dict(os.environ, {device._EXPECT_ENV: "1"}), \
                mock.patch.dict(sys.modules, {"torch": _torch(cuda=False)}), \
                self.assertLogs("vigent.device", level="CRITICAL") as logs:
            os.environ.pop(device._ENV, None)
            dev1 = device.pick_device()
            dev2 = device.pick_device()            # 두 번째 슬롯 — 로그는 한 번만
        self.assertEqual((dev1, dev2), ("cpu", "cpu"))
        st = device.gpu_fallback_status()
        self.assertTrue(st["expected_gpu"]); self.assertTrue(st["fallback"])
        self.assertIn("is_available", st["fallback_reason"])
        self.assertEqual(len(logs.records), 1, "CRITICAL 은 첫 발생 1회여야 한다(슬롯마다 반복 금지)")

    def test_expected_gpu_with_cuda_is_quiet(self):
        with mock.patch.dict(os.environ, {device._EXPECT_ENV: "1"}), \
                mock.patch.dict(sys.modules, {"torch": _torch(cuda=True)}):
            os.environ.pop(device._ENV, None)
            self.assertEqual(device.pick_device(), "cuda")
        st = device.gpu_fallback_status()
        self.assertTrue(st["expected_gpu"]); self.assertFalse(st["fallback"])

    def test_no_expectation_keeps_old_behavior(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.dict(sys.modules, {"torch": _torch(cuda=False)}):
            os.environ.pop(device._EXPECT_ENV, None); os.environ.pop(device._ENV, None)
            with self.assertNoLogs("vigent.device", level="WARNING"):
                self.assertEqual(device.pick_device(), "cpu")
        self.assertFalse(device.gpu_fallback_status()["fallback"])

    def test_forced_cpu_under_expectation_is_still_loud(self):
        """VIGENT_DETECT_DEVICE=cpu 로 강제해도 GPU 빌드면 알린다 — 강제는 기대를 지우지 않는다."""
        with mock.patch.dict(os.environ, {device._EXPECT_ENV: "1", device._ENV: "cpu"}), \
                mock.patch.dict(sys.modules, {"torch": _torch(cuda=True)}), \
                self.assertLogs("vigent.device", level="CRITICAL"):
            self.assertEqual(device.pick_device(), "cpu")
        self.assertIn("강제", device.gpu_fallback_status()["fallback_reason"])


class HealthGpuBlock(unittest.TestCase):
    def test_health_exposes_fallback_keys(self):
        import main
        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            g = c.get("/health").json().get("gpu") or {}
        for k in ("expected_gpu", "fallback", "fallback_reason"):
            self.assertIn(k, g)
        self.assertIsInstance(g["fallback"], bool)


if __name__ == "__main__":
    unittest.main()
