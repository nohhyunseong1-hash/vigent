"""[I-1] 포터블 프로필 치환 — 빌드 종류(CPU/GPU)·현장 프로파일(없음/academy)별 결과를 고정한다.

★왜 이 테스트가 필요한가
  `deploy/portable/portable_overrides.yaml` 의 `detect.backend` 치환은 **CPU 빌드에서만**
  이득이다. CPU 전용 torch 에서는 onnx 가 1.85배 빠르지만(benchmarks/onnx_cpu_bench.md),
  GPU 빌드에서 onnx-cpu 를 쓰면 4채널 인수시험 `age ok 비율` 이 0.467 로 **미달**한다
  (실측: docs/deploy/bench_4ch_2026-09-23.md — 추론 797ms vs torch 59.9ms).
  그래서 `skip_when_gpu: true` 로 GPU 빌드에서는 치환을 건너뛴다.
  이 규칙이 조용히 뒤집히면 **현장에서 성능이 무너지는데 설정 파일만 봐서는 모른다.**

★[CODE_AUDIT_20260928 #3] 학원 결정(근골격 OFF·화재 OFF)은 `deploy/academy/portable_overrides.academy.yaml` 로 분리됐다.
  기본(프로파일 없음) 포터블은 전역값(근골격 ON·화재 ON)이고, `-Profile academy` 일 때만 두 항목이 덧붙는다.

이 테스트는 빌드 스크립트가 쓰는 것과 **같은 치환 규칙**을 적용해 결과를 확인한다
(PowerShell 을 띄우지 않고 로직만 재현 — CI 에서 OS 에 의존하지 않게).
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_OV = _ROOT / "deploy" / "portable" / "portable_overrides.yaml"
_OV_ACADEMY = _ROOT / "deploy" / "academy" / "portable_overrides.academy.yaml"
_FILES = {"tuning": "config/tuning.yaml", "vision": "themes/safety/vision.yaml"}


def apply_profile(gpu: bool, profile: str = "") -> dict[str, str]:
    """build_portable.ps1 의 apply_profile.py 와 같은 규칙으로 치환한 텍스트를 돌려준다(프로파일 오버라이드는 덧붙임)."""
    o = yaml.safe_load(_OV.read_text(encoding="utf-8")) or {}
    if profile:
        o.update(yaml.safe_load((_ROOT / "deploy" / profile / f"portable_overrides.{profile}.yaml").read_text(encoding="utf-8")) or {})
    out: dict[str, str] = {}
    for fkey, rel in _FILES.items():
        items = [(k, v) for k, v in o.items()
                 if (v.get("file") or "tuning") == fkey and not (gpu and v.get("skip_when_gpu"))]
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


class PortableDefaultIsGlobal(unittest.TestCase):
    """★[CODE_AUDIT #3] 프로파일 없는 포터블 = 전역값. 학원 결정이 기본으로 구워지지 않는다."""

    def test_only_backend_differs_between_cpu_and_gpu(self):
        cpu, gpu = apply_profile(gpu=False), apply_profile(gpu=True)
        self.assertEqual(set(cpu), set(gpu))
        self.assertEqual(cpu["themes/safety/vision.yaml"], gpu["themes/safety/vision.yaml"])

    def test_ergonomics_on_and_fire_smoke_on_by_default(self):
        for gpu in (False, True):
            v = yaml.safe_load(apply_profile(gpu=gpu)["themes/safety/vision.yaml"])
            self.assertIn("joints", v["judgment"]["ergonomics"], "기본 포터블은 근골격 규칙 ON(전역값)")
            t = apply_profile(gpu=gpu)["config/tuning.yaml"]
            self.assertNotIn("include_fire_smoke: 0", t, "기본 포터블은 화재 감시 ON(전역값)")


class AcademyProfileAddsSiteDecisions(unittest.TestCase):
    def test_academy_turns_ergonomics_and_fire_off_in_both_builds(self):
        for gpu in (False, True):
            r = apply_profile(gpu=gpu, profile="academy")
            erg = yaml.safe_load(r["themes/safety/vision.yaml"])["judgment"]["ergonomics"]
            self.assertNotIn("joints", erg); self.assertIn("joints_off_portable", erg)
            self.assertIn("include_fire_smoke: 0", r["config/tuning.yaml"])

    def test_academy_keeps_backend_rule(self):
        self.assertIn("backend: onnx-cpu", apply_profile(gpu=False, profile="academy")["config/tuning.yaml"])
        self.assertIn("backend: torch ", apply_profile(gpu=True, profile="academy")["config/tuning.yaml"])

    def test_academy_file_has_no_platform_items(self):
        o = yaml.safe_load(_OV_ACADEMY.read_text(encoding="utf-8"))
        self.assertNotIn("detect.backend", o)


if __name__ == "__main__":
    unittest.main()
