"""현장 초벌 라벨러(scripts/data/field_prelabel.py) — 합성 mp4·사진 + 가짜 예측기. [PPE v2 현장 경로, 2026-09-27]

★무엇을 고정하는가
  1. 2fps 추출: 10fps 3초 영상 → step 5 → 6프레임. fps 못 읽으면 25 가정(step 12).
  2. 이름 규칙: <카메라>__<YYYYMMDD>__<day|night>__<원본 stem>__f<번호> — 카메라는 폴더명, 날짜·주야는 파일명에서.
  3. 사람 없는 프레임은 negatives/ 로(라벨 없음), 있는 프레임은 images/+labels/+labels_meta/ + CVAT 1.1 XML(카메라별, source="auto", conf 속성).
  4. 규칙 11: manifest 카운트 = 디스크 파일 수. 5. 저장소 안 출력 폴더는 거부.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "data"))

import field_fixture as FX  # noqa: E402
import field_prelabel as P  # noqa: E402


def fake_predictor(im):
    """가짜 v1: 폭이 300 이상인 이미지(영상 프레임·사진 모두 320)에서 프레임 밝기로 사람 유무를 가른다 — 평균 밝기 ≥100 이면 사람 없음."""
    import numpy as np
    arr = np.asarray(im); mean = float(arr.mean())
    if mean >= 100:
        return [("Hardhat", [10.0, 10.0, 30.0, 30.0], 0.9)]          # 사람 없이 안전모만 → 음성 처리돼야 한다
    return [("person", [40.0, 60.0, 100.0, 200.0], 0.95), ("NO-Hardhat", [50.0, 60.0, 90.0, 90.0], 0.5), ("Safety-Vest", [45.0, 90.0, 95.0, 150.0], 0.3)]


class PrelabelTest(unittest.TestCase):
    def test_frame_step_and_names(self):
        self.assertEqual(P.frame_step(10.0), 5); self.assertEqual(P.frame_step(25.0), 12); self.assertEqual(P.frame_step(0.0), 12); self.assertEqual(P.frame_step(1.0), 1)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); f = root / "cam3_gate" / "20261005_143000_day_A.mp4"; f.parent.mkdir(); f.write_bytes(b"x")
            w = P.parse_when(f, root); self.assertEqual((w["date"], w["hour"], w["date_source"]), ("20261005", 14, "name"))
            self.assertEqual(P.daynight_of(f, root, w["hour"]), ("day", "name"))
            g = root / "cam1" / "night" / "clip.avi"; g.parent.mkdir(parents=True); g.write_bytes(b"x")
            self.assertEqual(P.daynight_of(g, root, None)[0], "night"); self.assertEqual(P.parse_when(g, root)["date_source"], "mtime")
            self.assertEqual(P.daynight_of(g, root, 3, override="day"), ("day", "cli")); self.assertEqual(P.camera_of(g, root), "cam1")
            self.assertEqual(P.daynight_of(root / "x.jpg", root, 22)[0], "night"); self.assertEqual(P.daynight_of(root / "x.jpg", root, None)[0], "unk")

    def test_run_end_to_end_with_fake_predictor(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"; FX.make_raw(raw, cams=2, seconds=3, fps=10)
            out = Path(td) / "out"
            m = P.run(raw, out, fake_predictor, conf=0.4)
            c = m["counts"]
            self.assertEqual(c["videos"], 2); self.assertEqual(c["images"], 4)
            self.assertEqual(c["positive"] + c["negative"], 2 * 6 + 4)                       # 3초×10fps → 6프레임/영상
            self.assertTrue(m["verified"])
            self.assertEqual(len(list((out / "images").glob("*.jpg"))), c["positive"]); self.assertEqual(len(list((out / "labels").glob("*.txt"))), c["positive"])
            self.assertEqual(len(list((out / "negatives").glob("*.jpg"))), c["negative"]); self.assertGreater(c["negative"], 0); self.assertGreater(c["positive"], 0)
            stems = [f["stem"] for f in m["frames"]]
            self.assertTrue(any(s.startswith("cam1_test__20261001__day__") and "__f" in s for s in stems), stems[:3])
            self.assertTrue(any(s.startswith("cam2_test__20261002__night__") for s in stems))
            # 라벨: conf 0.3 짜리 Safety-Vest 는 빠지고(≥0.4) person·NO-Hardhat 만
            lb = next((out / "labels").glob("*.txt")).read_text(encoding="utf-8").splitlines()
            self.assertEqual(sorted(int(ln.split()[0]) for ln in lb), [0, 2])
            # CVAT 1.1 XML: 카메라별, source=auto, conf 속성, 이미지 수 = 그 카메라 양성 수
            xmls = sorted((out / "cvat").glob("*.xml")); self.assertEqual([x.stem for x in xmls], ["cam1_test", "cam2_test"])
            tree = ET.parse(xmls[0]); r = tree.getroot()
            self.assertEqual(r.findtext("version"), "1.1")
            imgs = r.findall("image"); self.assertEqual(len(imgs), sum(1 for f in m["frames"] if f["camera"] == "cam1_test" and not f["negative"]))
            box = imgs[0].find("box"); self.assertEqual(box.get("source"), "auto"); self.assertIn(box.get("label"), P.CLASSES)
            self.assertEqual(box.find("attribute").get("name"), "conf")
            labels = [lb.findtext("name") for lb in r.find("meta").find("task").find("labels")]; self.assertEqual(labels, P.CLASSES)
            meta = json.loads(next((out / "labels_meta").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(meta["prelabel"], {"model": "ppe_rfdetr_v1", "conf": 0.4}); self.assertIn(meta["daynight"], ("day", "night"))
            self.assertEqual((out / "classes.txt").read_text(encoding="utf-8").split(), P.CLASSES)

    def test_refuses_output_inside_repo_and_dry_run(self):
        with self.assertRaises(SystemExit):
            P.assert_private_out(_ROOT / "audit" / "x")
        P.assert_private_out(Path(tempfile.gettempdir()) / "vigent_field_x")           # 저장소 밖 → 통과
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw"; FX.make_raw(raw, cams=1)
            m = P.run(raw, Path(td) / "out", None, dry_run=True)
            self.assertTrue(m["dry_run"]); self.assertEqual(len(m["inputs"]), 3); self.assertFalse((Path(td) / "out").exists())


if __name__ == "__main__":
    unittest.main()
