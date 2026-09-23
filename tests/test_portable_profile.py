"""[I-1] 포터블 프로필 치환 — 빌드 종류(CPU/GPU)별 결과를 고정한다.

★왜 이 테스트가 필요한가
  `deploy/portable/portable_overrides.yaml` 의 `detect.backend` 치환은 **CPU 빌드에서만**
  이득이다. CPU 전용 torch 에서는 onnx 가 1.85배 빠르지만(benchmarks/onnx_cpu_bench.md),
  GPU 빌드에서 onnx-cpu 를 쓰면 4채널 인수시험 `age ok 비율` 이 0.467 로 **미달**한다
  (실측: docs/deploy/bench_4ch_2026-09-23.md — 추론 797ms vs torch 59.9ms).
  그래서 `skip_when_gpu: true` 로 GPU 빌드에서는 치환을 건너뛴다.
  이 규칙이 조용히 뒤집히면 **현장에서 성능이 무너지는데 설정 파일만 봐서는 모른다.**

이 테스트는 빌드 스크립트가 쓰는 것과 **같은 치환 규칙**을 적용해 결과를 확인한다
(PowerShell 을 띄우지 않고 로직만 재현 — CI 에서 OS 에 의존하지 않게).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_OV = _ROOT / "deploy" / "portable" / "portable_overrides.yaml"
_FILES = {"tuning": "config/tuning.yaml", "vision": "themes/safety/vision.yaml"}


def apply_profile(gpu: bool) -> dict[str, str]:
    """build_portable.ps1 의 apply_profile.py 와 같은 규칙으로 치환한 텍스트를 돌려준다."""
    o = yaml.safe_load(_OV.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for fkey, rel in _FILES.items():
        items = [(k, v) for k, v in o.items()
                 if (v.get("file") or "tuning") == fkey and not (gpu and v.get("skip_when_gpu"))]
        if not items:
            continue
        t = (_ROOT / rel).read_text(encoding="utf-8")
        for k, v in items:
            n = t.count(v["from"])
            assert n == 1, f"{k}: 원본({rel})에서 {v['from']!r} 가 {n}곳 (정확히 1곳이어야 함)"
            t = t.replace(v["from"], v["to"], 1)
        out[rel] = t
    return out


class PortableProfileBackend(unittest.TestCase):
    def test_cpu_build_uses_onnx_cpu(self):
        t = apply_profile(gpu=False)["config/tuning.yaml"]
        self.assertIn("backend: onnx-cpu", t,
                      "CPU 빌드는 onnx-cpu 여야 한다(CPU torch 대비 1.85배 빠름)")
        self.assertNotIn("backend: torch ", t)

    def test_gpu_build_keeps_torch(self):
        t = apply_profile(gpu=True)["config/tuning.yaml"]
        self.assertIn("backend: torch ", t,
                      "GPU 빌드는 torch 여야 한다 — onnx-cpu 는 4채널 age ok 0.467 로 인수시험 미달")
        self.assertNotIn("backend: onnx-cpu", t)

    def test_backend_item_is_marked_skip_when_gpu(self):
        """표시가 사라지면 GPU 빌드가 조용히 onnx-cpu 로 돌아간다 — 그걸 막는다."""
        o = yaml.safe_load(_OV.read_text(encoding="utf-8"))
        self.assertTrue(o["detect.backend"].get("skip_when_gpu"),
                        "detect.backend 에 skip_when_gpu 가 없다")


class PortableProfileOtherItemsUnchanged(unittest.TestCase):
    """★backend 말고는 GPU/CPU 가 같아야 한다 — 분기가 다른 항목에 번지지 않았는지 확인."""

    def test_only_backend_differs(self):
        cpu, gpu = apply_profile(gpu=False), apply_profile(gpu=True)
        self.assertEqual(set(cpu), set(gpu))
        for rel in cpu:
            if rel == "config/tuning.yaml":
                continue
            self.assertEqual(cpu[rel], gpu[rel], f"{rel} 가 빌드 종류에 따라 달라졌다")

    def test_ergonomics_off_in_both(self):
        for gpu in (False, True):
            v = yaml.safe_load(apply_profile(gpu=gpu)["themes/safety/vision.yaml"])
            erg = v["judgment"]["ergonomics"]
            self.assertNotIn("joints", erg)
            self.assertIn("joints_off_portable", erg)

    def test_fire_smoke_off_in_both(self):
        for gpu in (False, True):
            t = apply_profile(gpu=gpu)["config/tuning.yaml"]
            self.assertIn("include_fire_smoke: 0", t)


if __name__ == "__main__":
    unittest.main()
