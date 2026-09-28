"""CODE_AUDIT_20260928 #6 — 코드 기본값 = yaml, 키 누락 WARN, 히스테리시스 초기화 순서. [2026-09-28]

★무엇을 고정하는가
  ① defaults.py 의 RES·CONF 가 config/tuning.yaml 의 detect.imgsz·detect.conf 와 같다(둘 중 하나만 바꾸면 여기서 잡힌다).
  ② guard 클래스 상수(DETECTOR_CONF·IMGSZ·DEFAULT_CONF)와 어댑터·서비스 폴백이 defaults 를 쓴다.
  ③ tuning 에 detect.conf/imgsz 가 없으면 기본값으로 돌되 TUNING_WARN + WARNING 로그로 드러난다.
  ④ detect.hysteresis_frames>0 이면 GuardAgent 초기화가 실패하지 않고 값이 반영된다(예전: AttributeError / 덮어쓰기).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import defaults  # noqa: E402
import vision_loader  # noqa: E402
from agents import guard as guard_mod  # noqa: E402


class DefaultsMatchYaml(unittest.TestCase):
    def test_values_equal_tuning_yaml(self):
        t = yaml.safe_load((_ROOT / "config" / "tuning.yaml").read_text(encoding="utf-8"))
        d = t["detect"]
        self.assertEqual(defaults.RES, int(d["imgsz"]))
        for k, v in defaults.CONF.items():
            self.assertEqual(float(d["conf"][k]), v, f"detect.conf.{k}")
        self.assertEqual(defaults.PERSON_THRESHOLD, defaults.CONF["person"])

    def test_guard_and_adapter_use_defaults(self):
        self.assertEqual(guard_mod.GuardAgent.DETECTOR_CONF, defaults.CONF)
        self.assertEqual(guard_mod.GuardAgent.IMGSZ, defaults.RES)
        self.assertEqual(guard_mod.GuardAgent.DEFAULT_CONF, defaults.DEFAULT_CONF)
        src = (_ROOT / "vigent-core" / "detectors" / "rfdetr_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("or 384", src); self.assertIn("_defaults.RES", src)
        svc = (_ROOT / "vigent-core" / "rfdetr_service.py").read_text(encoding="utf-8")
        self.assertIn("PERSON_THRESHOLD", svc)


class TuningGaps(unittest.TestCase):
    """tuning 모듈을 갈아끼우지 않고(세그폴트) section/val 만 패치한다 — test_guard_tuning_partial_failure 와 같은 방식."""

    def _guard(self, detect: dict):
        import tuning
        real_section, real_val = tuning.section, tuning.val

        def fake_section(name):
            return dict(detect) if name == "detect" else real_section(name)

        def fake_val(sec, key, default, env=None):
            if sec == "detect":
                return detect.get(key, default)
            return real_val(sec, key, default, env)
        with mock.patch.object(tuning, "section", side_effect=fake_section), mock.patch.object(tuning, "val", side_effect=fake_val):
            return guard_mod.GuardAgent(vision_loader.load_vision("safety"))

    def test_missing_conf_and_imgsz_warns_and_uses_defaults(self):
        with self.assertLogs("vigent.guard", level="WARNING") as cm:
            g = self._guard({})
        self.assertEqual(g.DETECTOR_CONF, defaults.CONF); self.assertEqual(g.IMGSZ, defaults.RES)
        self.assertTrue(any("설정 누락" in m for m in cm.output))
        self.assertTrue(any("detect.conf 키 누락" in w for w in g.TUNING_WARN))

    def test_present_keys_no_gap_warning(self):
        g = self._guard({"imgsz": 384, "conf": dict(defaults.CONF)})
        self.assertFalse(any("누락" in w for w in g.TUNING_WARN), g.TUNING_WARN)

    def test_hysteresis_frames_applies_without_error(self):
        g = self._guard({"imgsz": 384, "conf": dict(defaults.CONF), "hysteresis_frames": 2})
        self.assertEqual(set(g.HYSTERESIS.values()), {2}); self.assertEqual(set(g.HYSTERESIS), set(g.HYSTERESIS_FRAMES))
        g0 = self._guard({"imgsz": 384, "conf": dict(defaults.CONF)})
        self.assertEqual(g0.HYSTERESIS, g0.HYSTERESIS_FRAMES)


if __name__ == "__main__":
    unittest.main()
