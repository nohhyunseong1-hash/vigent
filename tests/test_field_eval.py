"""평가 하네스의 현장 held-out 확장(scripts/eval/eval_v1_heldout.py) — 가짜 예측기로 채점기·음성 오탐·합격선·표를 고정한다. [2026-09-27]

★무엇을 고정하는가
  1. score_items: 클래스별 gt/tp/fp/fn·R/P(Wilson)·AP50 이 손으로 센 값과 같다(운용 임계 이상만 P/R, AP 는 0.05 이상 전부).
  2. load_field_heldout: heldout.json 의 frames/negatives → 이미지+GT(YOLO→CSS 이름). 3. negative_fp: 음성 프레임 오탐률.
  4. field_goal_check / render_three_sets: 합격선 NO-Hardhat R≥85 · NO-SV R≥90 · 음성 오탐 ≤1% 행이 표에 나오고 판정이 맞다.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval")); sys.path.insert(0, str(_ROOT / "scripts" / "data"))

import eval_v1_heldout as E  # noqa: E402
import field_fixture as FX  # noqa: E402


class ScoreItemsTest(unittest.TestCase):
    def test_counts_match_hand_count(self):
        with tempfile.TemporaryDirectory() as td:
            from PIL import Image
            p1 = Path(td) / "a.jpg"; Image.new("RGB", (100, 100)).save(p1); p2 = Path(td) / "b.jpg"; Image.new("RGB", (100, 100)).save(p2)
            items = [(p1, [("Person", [10, 10, 50, 90]), ("NO-Hardhat", [20, 10, 40, 30])]), (p2, [("Person", [10, 10, 50, 90])])]
            preds = {p1.name: [("Person", [10, 10, 50, 90], 0.9), ("NO-Hardhat", [60, 60, 80, 80], 0.8), ("NO-Hardhat", [20, 10, 40, 30], 0.2)],
                     p2.name: [("Person", [12, 10, 50, 88], 0.6)]}
            calls = []

            def predict(im):
                calls.append(1); return preds[items[len(calls) - 1][0].name]
            r = E.score_items(predict, items, ["Person", "NO-Hardhat", "NO-Safety Vest"], op_conf=0.35, say=lambda *a: None)
            rows = {x["class"]: x for x in r["rows"]}
            self.assertEqual((rows["Person"]["tp"], rows["Person"]["fp"], rows["Person"]["fn"]), (2, 0, 0)); self.assertEqual(rows["Person"]["recall"], 100.0)
            self.assertEqual((rows["NO-Hardhat"]["tp"], rows["NO-Hardhat"]["fp"], rows["NO-Hardhat"]["fn"]), (0, 1, 1))     # 0.2 짜리 정답 박스는 운용점 미만
            self.assertEqual(rows["NO-Hardhat"]["recall"], 0.0); self.assertEqual(rows["NO-Hardhat"]["ap50"], 50.0)         # AP 는 0.05 이상 전부(0.8 FP 뒤 0.2 TP)
            self.assertIsNone(rows["NO-Safety Vest"]["recall"]); self.assertEqual(r["images"], 2)

    def test_field_heldout_loading_negatives_and_goals(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "prelabel"; FX.make_vigent(d, cams=2, clips=2, frames=10, heldout_n=6)
            items, negs, info = E.load_field_heldout(d)
            self.assertEqual(len(items), info["n_positive_listed"]); self.assertEqual(len(negs), info["n_negative_listed"]); self.assertGreater(len(negs), 0)
            self.assertTrue(all(g[0] in ("Person", "Hardhat", "NO-Hardhat", "Safety Vest", "NO-Safety Vest") for _, gts in items for g in gts))
            # 완벽 예측기: GT 그대로(채점기는 items 순서로 호출한다) → R=P=100, 음성에서는 아무것도 안 냄 → 오탐 0
            order = iter(items)
            perfect = lambda im: [(n, b, 0.9) for n, b in next(order)[1]]  # noqa: E731
            names = ["Person", "Hardhat", "NO-Hardhat", "Safety Vest", "NO-Safety Vest"]
            r = E.score_items(perfect, items, names, 0.35, say=lambda *a: None)
            self.assertEqual({x["class"]: x["recall"] for x in r["rows"] if x["gt"]}, {c: 100.0 for c in {x["class"] for x in r["rows"] if x["gt"]}})
            neg = E.negative_fp(lambda im: [], negs, 0.35, say=lambda *a: None); self.assertEqual((neg["fp_images"], neg["neg_fp_rate"]), (0, 0.0))
            noisy = lambda im: [("Hardhat", [1, 1, 20, 20], 0.5)]  # noqa: E731
            neg2 = E.negative_fp(noisy, negs, 0.35, say=lambda *a: None); self.assertEqual(neg2["neg_fp_rate"], 100.0); self.assertEqual(neg2["fp_boxes_by_class"], {"Hardhat": len(negs)})
            field = {"rows": r["rows"], "negatives": neg, "op_conf": 0.35, "field": info}
            checks = {c["class"]: c["verdict"] for c in E.field_goal_check(field)}
            self.assertTrue(checks["NO-Hardhat"].startswith("달성")); self.assertTrue(checks["NO-Safety Vest"].startswith("달성")); self.assertEqual(checks["(negatives)"], "달성")
            field2 = dict(field); field2["negatives"] = neg2
            self.assertEqual({c["class"]: c["verdict"] for c in E.field_goal_check(field2)}["(negatives)"], "미달")
            table = E.render_three_sets(None, None, "v2", None, field)
            self.assertIn("현장 held-out", table); self.assertIn("≥85.0", table); self.assertIn("≥90.0", table); self.assertIn("≤1.0", table); self.assertIn("프레임 오탐률", table)
            self.assertIn("미확보", E.render_three_sets(None, None, "v2", None, None))


if __name__ == "__main__":
    unittest.main()
