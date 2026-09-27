"""aihubshell 트리 파서·라벨 zip 선택(scripts/data/aihub_filetree.py). [2026-09-27]

★고정하는 것: 507식 이름(TL_/VS_)도, 163식 구형 명명(파일명은 '1.공동주택.zip', 구분은 상위 폴더 '라벨링데이터_…'/'원천데이터(zip)')도 경로로 라벨/원천을 가른다.
  가장 작은 라벨 zip 선택은 상한(GB) 안에서, 없으면 전체 중 최소.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "data"))

import aihub_filetree as T  # noqa: E402

TREE = """==========================================
aihubshell version 25.09.19 v0.6
Fetching file tree structure...
The contents are encoded in UTF-8 including Korean characters.
=================공지사항===================
    └─105.공사현장 안전장비 인식 데이터
        └─01.데이터
            ├─1.Training
            │  ├─원천데이터_210818_add
            │  │  ├─2.공연장_부산.zip | 1 GB | 559886
            │  │  └─1.공동주택
            │  │      └─1.공동주택_동탄.zip | 207 MB | 559895
            │  └─라벨링데이터_241008_add
            │      ├─2.공연장.zip | 5 MB | 559926
            │      └─1.공동주택.zip | 739 MB | 559924
            └─2.Validation
                ├─원천데이터(zip)
                │  └─VS_01_개구부작업.zip | 488 MB | 68032
                └─라벨링데이터(zip)_241008_add
                    ├─2.공연장.zip | 142 KB | 559944
                    └─TL_01_개구부작업.zip | 5 MB | 68026
"""


class FiletreeTest(unittest.TestCase):
    def test_parse_paths_and_classify(self):
        items = T.parse_tree(TREE)
        by = {i["key"]: i for i in items}
        self.assertEqual(len(items), 7)
        self.assertEqual(by["559895"]["path"], "105.공사현장 안전장비 인식 데이터/01.데이터/1.Training/원천데이터_210818_add/1.공동주택")
        self.assertEqual(by["559895"]["size_bytes"], 207 * 1024 ** 2)
        self.assertEqual(T.classify(by["559895"]), "원천(추정)")        # 구형 명명: 상위 폴더 '원천데이터'
        self.assertEqual(T.classify(by["559924"]), "라벨(추정)")        # 상위 폴더 '라벨링데이터'
        self.assertEqual(T.classify(by["68032"]), "원천(추정)")         # 507식 VS_
        self.assertEqual(T.classify(by["68026"]), "라벨(추정)")         # 507식 TL_

    def test_pick_smallest_label_within_cap_else_min(self):
        items = T.parse_tree(TREE)
        self.assertEqual(T.pick_smallest_label(items, 2.0)["key"], "559944")      # 142 KB
        self.assertEqual(T.pick_smallest_label(items, 0.0001)["key"], "559944")   # 상한 안이 없으면 전체 최소
        self.assertIsNone(T.pick_smallest_label([i for i in items if T.classify(i) != "라벨(추정)"], 2.0))
        md = T.to_markdown(items, "t"); self.assertIn("| 559944 |", md); self.assertIn("추정", md)


if __name__ == "__main__":
    unittest.main()
