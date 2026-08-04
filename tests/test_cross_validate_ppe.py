"""Phase C 교차게이트(_cross_validate_ppe) 회귀 — PPE 는 사람과 결부될 때만 유지.

사람 없는 PPE(벽·의자 오탐) 폐기, 사람 몸에 겹친 미착용(NO-*)은 유지(재현율 불변) 보증.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
from agents.guard import _cross_validate_ppe  # noqa: E402


class TestCrossValidatePpe(unittest.TestCase):
    def test_no_person_discards_all_ppe(self):
        dets = [
            {"label": "NO-Hardhat", "conf": 0.6, "bbox": [0.1, 0.1, 0.2, 0.2], "detector": "ppe"},
            {"label": "NO-Mask", "conf": 0.5, "bbox": [0.7, 0.7, 0.8, 0.85], "detector": "ppe"},
        ]
        self.assertEqual(_cross_validate_ppe(dets, 0.15), [])

    def test_body_ppe_kept_wall_ppe_dropped(self):
        dets = [
            {"label": "person", "conf": 0.9, "bbox": [0.3, 0.2, 0.6, 0.9], "detector": "person"},
            {"label": "NO-Hardhat", "conf": 0.7, "bbox": [0.38, 0.22, 0.52, 0.35], "detector": "ppe"},
            {"label": "NO-Mask", "conf": 0.5, "bbox": [0.02, 0.02, 0.1, 0.1], "detector": "ppe"},
        ]
        labels = [d["label"] for d in _cross_validate_ppe(dets, 0.15)]
        self.assertIn("person", labels)
        self.assertIn("NO-Hardhat", labels)      # 몸에 겹친 미착용 = 유지(재현율 불변)
        self.assertNotIn("NO-Mask", labels)      # 멀리 떨어진 벽 오탐 = 폐기

    def test_non_ppe_untouched(self):
        dets = [
            {"label": "fire", "conf": 0.8, "bbox": [0.1, 0.1, 0.2, 0.2], "detector": "fire_smoke"},
            {"label": "forklift", "conf": 0.7, "bbox": [0.5, 0.5, 0.7, 0.8], "detector": "forklift"},
        ]
        self.assertEqual(len(_cross_validate_ppe(dets, 0.15)), 2)   # PPE 아닌 것은 사람 유무와 무관


if __name__ == "__main__":
    unittest.main()
