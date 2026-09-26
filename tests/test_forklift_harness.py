"""forklift 전/후 비교 하네스(scripts/eval/forklift_compare_harness.py) + Hardhat 준라벨 생성기(scripts/data/pseudo_hardhat.py). [2026-09-26]

★무엇을 고정하는가
  1. eval_510: AP50·운용점 P/R·이미지 단위 양성 검출률/음성 오탐률이 주입한 예측으로 맞게 계산된다.
  2. 목표 판정: AP50 ≥70 · 음성 오탐 ≤1% — 달성/미달/미측정, 구간 걸침 표기. 표에 전(v1)·후·참고(boda_ax, 후보 아님) 행이 있다.
  3. 학원 참고 집합: 현장 YOLO 박스와 IoU≥0.5 일치율이 conf 별로 계산된다.
  4. 준라벨: conf 컷·정규화·병합(두 번 돌려도 두 배로 붙지 않음)·미리보기 파일이 실제로 생긴다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval")); sys.path.insert(0, str(_ROOT / "scripts" / "data"))

import forklift_compare_harness as H  # noqa: E402
import pseudo_hardhat as P  # noqa: E402


class Eval510Test(unittest.TestCase):
    def test_eval_510_metrics(self):
        items = [("p1", [[0, 0, 100, 100]]), ("p2", [[200, 200, 300, 300]]), ("n1", []), ("n2", [])]
        preds = {"p1": [([2, 2, 98, 98], 0.9)],                         # TP @0.5
                 "p2": [([200, 200, 300, 300], 0.2)],                   # 있지만 운용점 아래 → FN@0.5, AP 에는 기여
                 "n1": [([0, 0, 50, 50], 0.8)],                         # 음성 오탐(conf≥0.5)
                 "n2": [([0, 0, 50, 50], 0.4)]}                         # 0.3 이상이지만 0.5 미만
        r = H.eval_510(items, lambda k: preds[k], op_conf=0.5)
        self.assertEqual((r["tp"], r["fp"], r["fn"]), (1, 1, 1))
        self.assertEqual(r["recall"], 50.0); self.assertEqual(r["precision"], 50.0)
        self.assertEqual(r["pos_images"], 2); self.assertEqual(r["neg_images"], 2)
        self.assertEqual(r["pos_detect_rate"], 50.0); self.assertEqual(r["neg_fp_rate"], 50.0); self.assertEqual(r["neg_fp_rate_03"], 100.0)
        self.assertEqual(r["ap50"], 75.0)          # conf 순: TP(0.9)·FP(0.8)·FP(0.4)·TP(0.2) → rec .5 에서 prec 1.0, rec 1.0 에서 0.5 → 전점 보간 AP 0.75
        self.assertEqual(len(r["recall_ci95"]), 2)

    def test_goal_check_and_render(self):
        self.assertTrue(all(g["verdict"] == "미측정" for g in H.goal_check(None)))
        cand = {"s510": {"ap50": 80.0, "neg_fp_rate": 0.5, "neg_fp_rate_ci95": [0.1, 2.0], "recall": 70.0, "recall_ci95": [60.0, 78.0], "precision": 90.0},
                "field": {"agree_iou50_rate_05": 60.0, "agree_iou50_rate_01": 70.0, "any_box_rate_05": 65.0}, "weights": "new.pth"}
        g = {x["metric"]: x["verdict"] for x in H.goal_check(cand)}
        self.assertEqual(g["ap50"], "달성"); self.assertEqual(g["neg_fp_rate@0.5"], "달성(구간 걸침)")
        bad = {"s510": {"ap50": 12.0, "neg_fp_rate": 91.4}}
        g2 = {x["metric"]: x["verdict"] for x in H.goal_check(bad)}
        self.assertEqual(g2["ap50"], "미달"); self.assertEqual(g2["neg_fp_rate@0.5"], "미달")
        md = H.render(None, cand, "fk_510")
        self.assertIn("전(v1)", md); self.assertIn("후(fk_510)", md); self.assertIn("boda_ax", md); self.assertIn("후보 아님", md)
        self.assertIn("--write-baseline", md); self.assertIn("80.0", md)
        md2 = H.render(cand, cand, "x")
        self.assertNotIn("--write-baseline", md2)

    def test_resolve_forklift_ids(self):
        self.assertIsNone(H.resolve_forklift_ids({0: "forklift"}))                    # v1: 단일 클래스인데 predict 는 id 1 → 전부
        self.assertEqual(H.resolve_forklift_ids({0: "person", 1: "forklift"}), {1})
        with self.assertRaises(SystemExit):
            H.resolve_forklift_ids({0: "person", 1: "truck"})

    def test_field_agreement(self):
        frames = [("a", [[0, 0, 100, 100]]), ("b", [[0, 0, 100, 100]]), ("c", [])]
        preds = {"a": [([0, 0, 100, 100], 0.9)], "b": [([500, 500, 600, 600], 0.95), ([1, 1, 99, 99], 0.2)], "c": [([0, 0, 9, 9], 0.7)]}
        r = H.eval_field_frames(frames, lambda k: preds[k], op_conf=0.5)
        self.assertEqual(r["ref_box_frames"], 2)
        self.assertEqual(r["agree_iou50_rate_05"], 50.0)     # a 만(b 는 고신뢰 박스가 엉뚱한 곳)
        self.assertEqual(r["agree_iou50_rate_01"], 100.0)    # b 의 0.2 박스는 겹친다
        self.assertEqual(r["any_box_rate_05"], 100.0)        # "박스가 나왔다"는 지게차 검출이 아니다 — 두 지표를 나란히 둔다


class PseudoHardhatTest(unittest.TestCase):
    def test_pseudo_boxes_and_merge_once(self):
        boxes = P.pseudo_boxes([([10, 20, 50, 60], 0.95), ([0, 0, 30, 30], 0.3), ([-5, 0, 40, 20], 0.7)], 200, 100, 0.6)
        self.assertEqual(len(boxes), 2)                                   # 0.3 은 컷
        self.assertEqual(boxes[0]["cls"], P.HARDHAT); self.assertEqual(boxes[0]["source"], "pseudo:v1"); self.assertTrue(boxes[0]["derived"])
        self.assertAlmostEqual(boxes[0]["box"][0], 30 / 200, places=5); self.assertAlmostEqual(boxes[0]["box"][3], 40 / 100, places=5)
        self.assertAlmostEqual(boxes[1]["box"][2], 40 / 200, places=5)    # 음수 좌표는 0 으로 잘린다
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "pseudo"; base = Path(td) / "vigent_507"
            (base / "labels").mkdir(parents=True); (base / "labels_meta").mkdir()
            (base / "labels" / "s1.txt").write_text("0 0.5 0.5 0.2 0.4\n", encoding="utf-8")
            (base / "labels_meta" / "s1.json").write_text(json.dumps({"source": "aihub:507", "boxes": [{"cls": 0}]}), encoding="utf-8")
            r1 = P.write_pseudo("s1", "s1.jpg", boxes, out, base); r2 = P.write_pseudo("s1", "s1.jpg", boxes, out, base)
            self.assertIs(r1["merged"], True); self.assertEqual(r2["merged"], "already")
            lines = (base / "labels" / "s1.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3); self.assertTrue(lines[1].startswith("1 "))              # 두 번 돌려도 3줄
            meta = json.loads((base / "labels_meta" / "s1.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(1 for b in meta["boxes"] if b.get("source") == "pseudo:v1"), 2)
            self.assertEqual((out / "labels" / "s1.txt").read_text(encoding="utf-8").count("\n"), 2)
            r3 = P.write_pseudo("s9", "s9.jpg", boxes, out, base)          # 기존 라벨 없는 stem 은 out 에만
            self.assertFalse(r3["merged"]); self.assertFalse((base / "labels" / "s9.txt").exists())

    def test_preview_draws_file(self):
        try:
            import cv2  # noqa: F401
            import numpy as np
        except Exception:  # noqa: BLE001
            self.skipTest("cv2 없음")
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "img.jpg"; dst = Path(td) / "pv.jpg"
            cv2.imwrite(str(src), np.zeros((100, 200, 3), np.uint8))
            ok = P.draw_preview(src, [{"box": [0.5, 0.5, 0.2, 0.4], "conf": 0.9}], dst, 200, 100)
            self.assertTrue(ok); self.assertGreater(dst.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
