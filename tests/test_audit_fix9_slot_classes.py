"""CODE_AUDIT_20260928 #9 — 슬롯 클래스 허용 목록 + 로드 시 class_names 검증(추론·평가 경로의 슬롯 가드). [2026-09-28]

★무엇을 고정하는가
  ① 어댑터: allowed_labels 밖 라벨(예: forklift 슬롯의 person)은 최종 검출에서 빠지고 dropped_by_allowlist 로 센다. None 이면 전부 통과.
  ② verify_slot_classes: 필수 라벨이 없으면 그 목록을 돌려준다(표기 차이 'Safety Vest'/'Safety-Vest' 는 같은 것).
  ③ guard._get_model: 커스텀 가중치의 class_names 에 필수 라벨이 없으면 슬롯을 None 으로 두고 _load_errors 에 "class_names 불일치" 를 남긴다.
  ④ safety·academy vision.yaml 둘 다 rfdetr_classes/rfdetr_required 를 갖고 forklift 는 [forklift] 만 허용한다.
  ⑤ 평가기(eval_v1_heldout.make_predictor) 는 우리 4클래스가 없는 가중치를 SystemExit 로 거부한다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

from agents import guard as guard_mod  # noqa: E402
from detectors import rfdetr_adapter as A  # noqa: E402


class _Det:
    def __init__(self, xyxy, cid, conf):
        self.xyxy, self.class_id, self.confidence = np.array(xyxy, dtype=float), np.array(cid), np.array(conf)


class _FakeModel:
    def __init__(self, names, dets):
        self.class_names = names; self._dets = dets; self.model_config = type("C", (), {"resolution": 384})()

    def predict(self, pil, threshold=0.0):
        return self._dets

    def optimize_for_inference(self):
        pass


def _adapter(names, dets, allowed):
    """RfdetrDetector 를 실제 rfdetr 로드 없이 만든다(__init__ 우회, 필드만 채움)."""
    d = A.RfdetrDetector.__new__(A.RfdetrDetector)
    d.model = _FakeModel(names, dets); d.resolution = 384; d.device = "cpu"
    d._ln = guard_mod.LABEL_NORMALIZE; d._junk = guard_mod.JUNK_LABELS; d._imgsz_warned = set()
    d._custom_names = list(names)
    d.allowed = ({guard_mod.LABEL_NORMALIZE.get(a, a) for a in allowed} if allowed is not None else None); d.dropped_by_allowlist = 0
    return d


IMG = np.zeros((100, 200, 3), dtype=np.uint8)


class AdapterAllowlist(unittest.TestCase):
    def test_forklift_slot_drops_person(self):
        dets = _Det([[10, 10, 50, 90], [60, 10, 150, 90]], [0, 1], [0.9, 0.8])
        d = _adapter(["person", "forklift"], dets, allowed=["forklift"])
        out = d.detect(IMG, 0.5)
        self.assertEqual([o["label"] for o in out], ["forklift"]); self.assertEqual(d.dropped_by_allowlist, 1)
        d2 = _adapter(["person", "forklift"], dets, allowed=None)
        self.assertEqual(sorted(o["label"] for o in d2.detect(IMG, 0.5)), ["forklift", "person"])

    def test_allowlist_uses_normalized_labels(self):
        dets = _Det([[10, 10, 50, 90]], [0], [0.9])
        d = _adapter(["Safety Vest"], dets, allowed=["Safety-Vest"])           # CSS 표기 vs 표준 표기
        self.assertEqual([o["label"] for o in d.detect(IMG, 0.5)], ["Safety-Vest"])


class VerifySlotClasses(unittest.TestCase):
    def test_missing_and_spelling(self):
        ln = guard_mod.LABEL_NORMALIZE
        self.assertEqual(A.verify_slot_classes(["person", "forklift"], ["forklift"], ln), [])
        self.assertEqual(A.verify_slot_classes(["a", "b"], ["forklift"], ln), ["forklift"])
        css = ["Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest", "Person", "Safety Cone", "Safety Vest", "machinery", "vehicle"]
        self.assertEqual(A.verify_slot_classes(css, guard_mod.RFDETR_REQUIRED_DEFAULT["ppe"], ln), [])
        self.assertEqual(A.verify_slot_classes(None, ["forklift"], ln), [])       # COCO(메타 없음) 는 검사 안 함
        self.assertEqual(A.verify_slot_classes(["person", "Hardhat"], ["Hardhat", "NO-Hardhat"], ln), ["NO-Hardhat"])


class GuardRefusesMismatchedCheckpoint(unittest.TestCase):
    def _guard(self):
        g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
        g._models = {}; g._slot_path = {}; g._load_errors = {}; g._backend = {"forklift": "rfdetr", "ppe": "rfdetr"}
        g._rfdetr_weights = {"forklift": "D:/x/fk.pth", "ppe": "D:/x/ppe.pth"}
        g._rfdetr_classes = dict(guard_mod.RFDETR_CLASSES_DEFAULT); g._rfdetr_required = dict(guard_mod.RFDETR_REQUIRED_DEFAULT)
        g.IMGSZ = 384
        return g

    def test_missing_required_label_marks_slot_none(self):
        g = self._guard()
        fake = _adapter(["a", "b"], _Det([], [], []), allowed=None)
        with mock.patch("detectors.rfdetr_adapter.RfdetrDetector", return_value=fake):
            with self.assertLogs("vigent.guard", level="ERROR"):
                m = g._get_model("forklift")
        self.assertIsNone(m); self.assertIn("class_names 불일치", g._load_errors["forklift"]); self.assertIn("forklift", g._load_errors["forklift"])

    def test_matching_checkpoint_loads(self):
        g = self._guard()
        fake = _adapter(["person", "forklift"], _Det([], [], []), allowed=["forklift"])
        with mock.patch("detectors.rfdetr_adapter.RfdetrDetector", return_value=fake) as ctor:
            m = g._get_model("forklift")
        self.assertIs(m, fake); self.assertNotIn("forklift", g._load_errors)
        self.assertEqual(ctor.call_args.kwargs.get("allowed_labels"), ["forklift"])


class ProfilesDeclareSlotClasses(unittest.TestCase):
    def test_both_profiles(self):
        for rel in ("themes/safety/vision.yaml", "deploy/academy/vision.academy.yaml"):
            v = yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))["perception"]
            self.assertEqual(v["rfdetr_classes"]["forklift"], ["forklift"], rel)
            self.assertEqual(v["rfdetr_required"]["ppe"], ["Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest"], rel)
            self.assertEqual(v["rfdetr_classes"], guard_mod.RFDETR_CLASSES_DEFAULT, rel)


class EvaluatorGuard(unittest.TestCase):
    def test_make_predictor_refuses_missing_classes(self):
        import eval_v1_heldout as E
        fake_mod = type("M", (), {})()
        fake_mod.RFDETRNano = lambda **k: _FakeModel(["forklift"], _Det([], [], []))
        with mock.patch.dict(sys.modules, {"rfdetr": fake_mod}), mock.patch.dict(sys.modules, {"torch": type("T", (), {"cuda": type("C", (), {"is_available": staticmethod(lambda: False)})()})()}):
            with self.assertRaises(SystemExit) as cm:
                E.make_predictor("x.pth", 384, ["Hardhat", "NO-Hardhat", "Safety Vest", "NO-Safety Vest"])
        self.assertIn("우리 클래스가 없다", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
