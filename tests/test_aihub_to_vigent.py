"""AI Hub → VIGENT 정답지 변환기(scripts/data/aihub_to_vigent.py) — 합성 JSON 3건. [A-3, 2026-09-26]

★무엇을 고정하는가
  1. 507: WO-04 → NO-Hardhat(박스 그대로) · UA-04 → person 승격 · WO-01 → person · WO-05 는 제외(집계만).
     Hardhat 파생은 옵션을 줄 때만 생기고 사이드카에 derived=true 로 표시된다([추정] 규칙).
  2. 510: WO-01/02 → person · WO-04 → forklift · 폴리곤은 외접 박스. 분할은 영상 단위.
  3. 분할 키가 양쪽에 있으면 누출 검사가 잡는다(exit 3) · 축소 증강 라벨 변환이 캔버스 좌표로 옮겨진다.
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "data"))

import aihub_to_vigent as A  # noqa: E402


def _j507(rid: str, seq: int, ann: list[dict], device: int = 1) -> dict:
    return {"Raw Data Info.": {"raw_data_ID": rid, "location_ID": rid.split("_")[1], "process_ID": "E", "situation_ID": "UA-04",
                               "situation_description": "x", "resolution": [1920, 1080], "device": device},
            "Source Data Info.": {"source_data_ID": f"{rid}_{seq:04d}", "frame": "00:00:01.00", "file_extension": "jpg"},
            "Learning Data Info.": {"json_data_ID": f"{rid}_{seq:04d}", "annotation": ann}}


def _j510(rid: str, seq: int, ann: list[dict]) -> dict:
    return {"Raw data Info.": {"raw_data_ID": rid, "location_ID": "G03", "process_ID": "I", "situation_ID": "UC-10",
                               "situation_description": "y", "resolution": [1920, 1080], "device": 1},
            "Source data Info.": {"source_data_ID": f"{rid}_{seq:04d}", "file_extension": "jpg"},
            "Learning data info.": {"json_data_ID": f"{rid}_{seq:04d}", "annotation": ann}}


class Convert507Test(unittest.TestCase):
    def test_mapping_and_derived_hardhat(self):
        fr = A.parse_frame(_j507("H-210825_A03_E_UA-04_101", 1, [
            {"class_id": "WO-04", "box": [100, 200, 60, 60]},        # 머리 박스 → NO-Hardhat
            {"class_id": "UA-04", "box": [80, 200, 100, 360]},       # 전신 → person
            {"class_id": "WO-05", "box": [90, 260, 80, 140]},        # 제외
        ]), "507")
        c = Counter()
        boxes = A.convert_frame(fr, "507", None, c)
        self.assertEqual([b["cls"] for b in boxes], [A.CLASSES.index("NO-Hardhat"), A.CLASSES.index("person")])
        cx, cy, w, h = boxes[0]["box"]
        self.assertAlmostEqual(cx, (100 + 30) / 1920, places=5); self.assertAlmostEqual(h, 60 / 1080, places=5)
        self.assertEqual(c["skip:WO-05"], 1); self.assertFalse(any(b["derived"] for b in boxes))
        # 시나리오 폴더 WO-01: 옵션 없으면 person 만, 옵션 주면 Hardhat 파생(derived=true, 상단 17%)
        fr2 = A.parse_frame(_j507("H-210717_E01_E_WS-20_101", 3, [{"class_id": "WO-01", "box": [434, 495, 248, 290]}]), "507")
        only_person = A.convert_frame(fr2, "507", None, Counter())
        self.assertEqual([b["cls"] for b in only_person], [0])
        with_hat = A.convert_frame(fr2, "507", 0.17, Counter())
        self.assertEqual([b["cls"] for b in with_hat], [0, A.CLASSES.index("Hardhat")])
        hat = with_hat[1]; self.assertTrue(hat["derived"]); self.assertIn("추정", hat["derive_rule"])
        self.assertAlmostEqual(hat["box"][3], 290 * 0.17 / 1080, places=5)      # 높이 = 사람 높이의 17%
        self.assertAlmostEqual(hat["box"][1], (495 + 290 * 0.17 / 2) / 1080, places=5)  # 상단 정렬


class Convert510AndSplitTest(unittest.TestCase):
    def test_510_mapping_polygon_and_video_split_with_leak_check(self):
        c = Counter()
        fr = A.parse_frame(_j510("L-210916_G03_I_UC-10_001", 1, [
            {"class_id": "WO-01", "type": "box", "coord": [10, 20, 30, 40]},
            {"class_id": "WO-04", "type": "polygon", "coord": [[100, 100], [300, 120], [280, 400], [90, 380]]},
            {"class_id": "SO-02", "type": "box", "coord": [0, 0, 5, 5]},
        ]), "510")
        boxes = A.convert_frame(fr, "510", None, c)
        self.assertEqual([b["cls"] for b in boxes], [0, A.CLASSES.index("forklift")])
        fx, fy, fw, fh = boxes[1]["box"]
        self.assertAlmostEqual(fw, (300 - 90) / 1920, places=5); self.assertAlmostEqual(fh, (400 - 100) / 1080, places=5)
        self.assertEqual(c["skip:SO-02"], 1)
        # 영상 단위 분할: 영상 5편 × 4프레임 → val 은 영상 단위로만 떨어진다
        frames = [{"stem": f"v{v}_{i}", "video": f"v{v}", "location_id": "G03"} for v in range(5) for i in range(4)]
        sp = A.split_by_key(frames, "video", 0.2, seed=1)
        self.assertEqual(len(sp["val_keys"]), 1); self.assertEqual(len(sp["val"]), 4)
        self.assertEqual(A.leak_check(sp, frames), [])
        sp_leak = dict(sp); sp_leak["val"] = sp["val"] + [sp["train"][0]]   # train 영상의 프레임을 val 에 섞는다
        self.assertTrue(A.leak_check(sp_leak, frames))


class ScaleAugAndEndToEndTest(unittest.TestCase):
    def test_scale_paste_moves_boxes_and_run_writes_files(self):
        from PIL import Image
        img = Image.new("RGB", (1920, 1080), (255, 255, 255))
        rnd = random.Random(0)
        canvas, nb = A.scale_paste(img, [[0.5, 0.5, 0.2, 0.4]], 0.25, (1920, 1080), rnd)
        self.assertEqual(canvas.size, (1920, 1080))
        self.assertAlmostEqual(nb[0][2], 0.2 * 0.25, places=5); self.assertAlmostEqual(nb[0][3], 0.4 * 0.25, places=5)
        self.assertTrue(0 <= nb[0][0] <= 1 and 0 <= nb[0][1] <= 1)
        # end-to-end: 507 라벨 2장소 → 파일·분할·누출 통과
        with tempfile.TemporaryDirectory() as td:
            lroot = Path(td) / "labels"; out = Path(td) / "out"
            for loc, n in (("A03", 3), ("B02", 3)):
                d = lroot / "공통"; d.mkdir(parents=True, exist_ok=True)
                for i in range(n):
                    rid = f"H-210825_{loc}_E_UA-04_{100 + i}"
                    (d / f"{rid}_0001.json").write_text(json.dumps(_j507(rid, 1, [
                        {"class_id": "WO-04", "box": [100, 200, 60, 60]}, {"class_id": "UA-04", "box": [80, 200, 100, 360]}])), encoding="utf-8")
            import argparse
            rc = A.run(argparse.Namespace(dataset="507", labels_root=str(lroot), images_root="", out=str(out), max_per_video=0,
                                          val_ratio=0.5, seed=1, hardhat_from_wo01=0.0, require_boxes=True, scale_aug="", scale_copies=1, dry_run=False))
            self.assertEqual(rc, 0)
            self.assertEqual(len(list((out / "labels").glob("*.txt"))), 6)
            sp = json.loads((out / "split.json").read_text(encoding="utf-8"))
            self.assertEqual(sp["key"], "location_id"); self.assertEqual(set(sp["train_keys"]) & set(sp["val_keys"]), set())
            meta = json.loads(next((out / "labels_meta").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(meta["source"], "aihub:507"); self.assertFalse(meta["image_present"])
            self.assertEqual((out / "classes.txt").read_text(encoding="utf-8").split(), A.CLASSES)


if __name__ == "__main__":
    unittest.main()
