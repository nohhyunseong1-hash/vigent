"""CODE_AUDIT_20260928 B-5 — 클래스 리스트·변환표 정본 labels.py, forklift 운용점 하나. [2026-09-28]

★무엇을 고정하는가
  ① labels.STD5/STD5_FORKLIFT/CSS_TO_STD/STD_TO_CSS/LABEL_NORMALIZE/PPE_MISSING_LABELS 값(예전 각 파일의 리터럴과 동일).
  ② 12곳이 정본에서 파생한다: guard·setup_wizard·incident·cvat_to_gt·field_fixture·field_prelabel·aihub_to_vigent·pseudo_hardhat·
     scan_507_unlabeled·finetune_rfdetr·eval_v1_heldout·aihub_smoke_eval — 각 모듈의 값이 labels 와 같고, 소스에 리터럴 복제가 없다.
  ③ 학습 설정 yaml 의 classes(5클래스 계약)는 STD5 와 같다(10클래스 CSS 설정은 별도 계약이라 제외).
  ④ forklift 운용점: defaults.FORKLIFT_OP_CONF == 학원 프로파일 conf.forklift · defaults.CONF["forklift"] == 전역 tuning conf.forklift ·
     평가 스크립트 4개의 conf 기본값 소스에 0.5 리터럴이 없다.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for d in ("vigent-core", "scripts/eval", "scripts/data", "scripts/train", "scripts/deploy"):
    sys.path.insert(0, str(_ROOT / d))

import labels  # noqa: E402

OLD_STD5 = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest"]
OLD_NORMALIZE = {"NO-Safety Vest": "NO-Safety-Vest", "Safety Vest": "Safety-Vest", "NO-Safety-Vest": "NO-Safety-Vest", "Safety-Vest": "Safety-Vest",
                 "Hardhat": "Hardhat", "NO-Hardhat": "NO-Hardhat", "Fire": "fire", "Person": "person", "PERSON": "person",
                 "Forklift": "forklift", "Smoke": "smoke"}


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


class Canonical(unittest.TestCase):
    def test_values_unchanged(self):
        self.assertEqual(labels.STD5, OLD_STD5); self.assertEqual(labels.STD5_FORKLIFT, OLD_STD5 + ["forklift"])
        self.assertEqual(labels.LABEL_NORMALIZE, OLD_NORMALIZE); self.assertEqual(list(labels.LABEL_NORMALIZE), list(OLD_NORMALIZE))
        self.assertEqual(labels.CSS_TO_STD, {"NO-Safety Vest": "NO-Safety-Vest", "Safety Vest": "Safety-Vest", "Person": "person"})
        self.assertEqual(labels.STD_TO_CSS, {"NO-Safety-Vest": "NO-Safety Vest", "Safety-Vest": "Safety Vest", "person": "Person"})
        self.assertEqual(labels.PPE_MISSING_LABELS, ("NO-Hardhat", "NO-Safety-Vest", "NO-Mask"))
        self.assertEqual(labels.std_name("Safety Vest"), "Safety-Vest"); self.assertEqual(labels.std_name("xyz"), "xyz")


class Derivations(unittest.TestCase):
    def test_modules_derive_from_labels(self):
        import aihub_to_vigent
        import cvat_to_gt
        import eval_v1_heldout
        import field_fixture
        import field_prelabel
        import finetune_rfdetr
        import scan_507_unlabeled
        import setup_wizard
        from agents import guard
        self.assertEqual(guard.LABEL_NORMALIZE, labels.LABEL_NORMALIZE); self.assertEqual(guard.PPE_MISSING_LABELS, set(labels.PPE_MISSING_LABELS))
        self.assertEqual(setup_wizard.PROFILES["default"]["required_ppe"], list(labels.PPE_MISSING_LABELS))
        self.assertEqual(cvat_to_gt.CLASSES, labels.STD5); self.assertEqual(field_fixture.CLASSES, labels.STD5); self.assertEqual(field_prelabel.CLASSES, labels.STD5)
        self.assertEqual(aihub_to_vigent.CLASSES, labels.STD5_FORKLIFT)
        self.assertEqual(scan_507_unlabeled.VEST, {"Safety Vest": "Safety-Vest", "NO-Safety Vest": "NO-Safety-Vest"})
        self.assertEqual(finetune_rfdetr.std_name("Person"), "person"); self.assertEqual(finetune_rfdetr._STD, labels.CSS_TO_STD)
        self.assertEqual(eval_v1_heldout.to_css_name("NO-Safety-Vest"), "NO-Safety Vest"); self.assertEqual(eval_v1_heldout._TO_CSS, labels.STD_TO_CSS)

    def test_no_literal_copies_in_sources(self):
        lit5 = re.compile(r'\[\s*"person",\s*"Hardhat",\s*"NO-Hardhat",\s*"Safety-Vest",\s*"NO-Safety-Vest"')
        for rel in ("scripts/eval/cvat_to_gt.py", "scripts/data/field_fixture.py", "scripts/data/field_prelabel.py", "scripts/data/aihub_to_vigent.py"):
            self.assertIsNone(lit5.search(_src(rel)), rel)
        lit_map = re.compile(r'"Safety Vest":\s*"Safety-Vest"')
        for rel in ("scripts/train/finetune_rfdetr.py", "scripts/data/pseudo_hardhat.py", "scripts/eval/scan_507_unlabeled.py", "scripts/eval/aihub_smoke_eval.py",
                    "vigent-core/agents/guard.py"):
            self.assertIsNone(lit_map.search(_src(rel)), rel)
        self.assertNotIn('"Safety-Vest": "Safety Vest"', _src("scripts/eval/eval_v1_heldout.py"))
        self.assertNotIn('"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"', _src("scripts/deploy/setup_wizard.py"))
        self.assertNotIn('"NO-Hardhat": "안전모 미착용"', _src("vigent-core/incident.py"))

    def test_training_configs_5class_contract(self):
        import yaml
        for f in sorted((_ROOT / "configs").glob("finetune_*.yaml")):
            cls = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("classes") or []
            if len(cls) == 5:
                self.assertEqual(cls, labels.STD5, f.name)


class ForkliftOperatingPoint(unittest.TestCase):
    def test_single_source(self):
        import defaults
        import yaml
        acad = yaml.safe_load((_ROOT / "deploy/academy/tuning.academy.yaml").read_text(encoding="utf-8"))
        glob_ = yaml.safe_load((_ROOT / "config/tuning.yaml").read_text(encoding="utf-8"))
        self.assertEqual(float(acad["detect"]["conf"]["forklift"]), defaults.FORKLIFT_OP_CONF)
        self.assertEqual(float(glob_["detect"]["conf"]["forklift"]), defaults.CONF["forklift"])
        for rel in ("scripts/eval/forklift_compare_harness.py", "scripts/eval/forklift_fp_dump.py", "scripts/eval/forklift_neg_eval.py", "scripts/eval/forklift_field_yardstick.py"):
            s = _src(rel)
            self.assertIn("_defaults.FORKLIFT_OP_CONF", s, rel)
            self.assertIsNone(re.search(r'(--conf[\w-]*", type=float, default=0\.5\b|op_conf: float = 0\.5\b|"op_conf": 0\.5\b)', s), rel)


if __name__ == "__main__":
    unittest.main()
