"""[CODE_REVIEW M2-5] 보호구 미착용 신호에 **어떤 항목**(NO-Hardhat/NO-Safety-Vest/NO-Mask)인지 실린다.

배경: signals["ppe_missing"] 은 bool 뿐이라 이벤트 note 가 "보호구 미착용 감지" 고정 — 운영자가
안전모인지 조끼인지 모른다. guard 는 이미 라벨을 갖고 있으므로 `ppe_missing_labels` 를 추가하고
worker note 에 붙인다. 기존 키(ppe_missing·ppe_conf)는 불변.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import agents.guard as guard_mod  # noqa: E402
import worker as W  # noqa: E402

_IMG = np.zeros((10, 10, 3), dtype=np.uint8)


class _PpeModel:
    def detect(self, image_bgr, conf=0.0, imgsz=None, augment=False):
        return [{"label": "person", "raw_label": "Person", "conf": 0.9, "bbox": [0.3, 0.2, 0.6, 0.9]},
                {"label": "NO-Hardhat", "raw_label": "NO-Hardhat", "conf": 0.8, "bbox": [0.4, 0.2, 0.5, 0.3]},
                {"label": "Safety-Vest", "raw_label": "Safety Vest", "conf": 0.8, "bbox": [0.35, 0.4, 0.55, 0.6]}]


def _guard():
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
    g._models = {"ppe": _PpeModel()}
    g._slot_path = {}
    g._load_errors = {}
    g._predict_fail_streak = {}
    g._slot_degraded = {}
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.HYSTERESIS = dict(g.HYSTERESIS_FRAMES)
    g._sig_streak = {}
    g.PERSON_ENSEMBLE = True
    g.TRACK_ALGO = "iou"
    return g


class PpeMissingLabels(unittest.TestCase):
    def test_labels_listed_after_hysteresis(self):
        g = _guard()
        for _ in range(g.HYSTERESIS["ppe_missing"]):
            out = g.detect(_IMG, detectors=["ppe"], track_key="t:ppe")
        sig = out["signals"]
        self.assertTrue(sig["ppe_missing"])
        self.assertEqual(sig["ppe_missing_labels"], ["NO-Hardhat"])
        self.assertNotIn("Safety-Vest", sig["ppe_missing_labels"])      # 착용 라벨은 아님

    def test_worker_note_names_the_item(self):
        out = {"detections": [], "person_count": 1,
               "signals": {"ppe_missing": True, "ppe_missing_labels": ["NO-Hardhat", "NO-Mask"]}}
        fired = W._derive(out, [], None)
        notes = [n for r, _l, n, _s in fired if r == "ppe_missing"]
        self.assertEqual(len(notes), 1)
        self.assertIn("NO-Hardhat", notes[0])
        self.assertIn("NO-Mask", notes[0])

    def test_worker_note_without_labels_is_unchanged(self):
        out = {"detections": [], "person_count": 1, "signals": {"ppe_missing": True}}
        fired = W._derive(out, [], None)
        self.assertEqual([n for r, _l, n, _s in fired if r == "ppe_missing"], ["보호구 미착용 감지"])


if __name__ == "__main__":
    unittest.main()
