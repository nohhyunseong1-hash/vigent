"""zone_tile 헬퍼 테스트 (B9 커밋①) — 코어 미연결, 스텁 detector 로 검증.

좌표변환(zone 크롭→원본 정규화)·필터(conf/label/높이)·foot_in_zone 판정.
detector 는 주입이라 RF-DETR 로드 없이 테스트.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import zone_tile  # noqa: E402

# 정규화 zone: x∈[0.2,0.5], y∈[0.5,0.9]
ZONE = [(0.2, 0.5), (0.5, 0.5), (0.5, 0.9), (0.2, 0.9)]


def _frame():
    return np.zeros((1000, 1000, 3), dtype=np.uint8)   # H=W=1000 (좌표 계산 단순화)


def _stub(dets):
    def fn(_img):
        return dets
    return fn


class TestZoneTileDetect(unittest.TestCase):
    def test_coordinate_mapping(self):
        # big(=크롭) 정규화 [0.5,0.5,0.6,0.8] → 원본 정규화로 정확히 매핑
        det = [{"label": "person", "bbox": [0.5, 0.5, 0.6, 0.8], "conf": 0.3}]
        out = zone_tile.zone_tile_detect(_frame(), ZONE, _stub(det))
        self.assertEqual(len(out), 1)
        bb = out[0]["bbox"]
        # zx0=200,zw=300,zy0=500,zh=400 → x:200+0.5*300=350→0.35 ; y:500+0.5*400=700→0.70 ...
        self.assertAlmostEqual(bb[0], 0.35, places=3)
        self.assertAlmostEqual(bb[1], 0.70, places=3)
        self.assertAlmostEqual(bb[2], 0.38, places=3)
        self.assertAlmostEqual(bb[3], 0.82, places=3)

    def test_conf_below_thr_filtered(self):
        det = [{"label": "person", "bbox": [0.5, 0.5, 0.6, 0.8], "conf": 0.05}]
        self.assertEqual(zone_tile.zone_tile_detect(_frame(), ZONE, _stub(det), thr=0.1), [])

    def test_non_person_filtered(self):
        det = [{"label": "car", "bbox": [0.5, 0.5, 0.6, 0.8], "conf": 0.9}]
        self.assertEqual(zone_tile.zone_tile_detect(_frame(), ZONE, _stub(det)), [])

    def test_tiny_height_filtered(self):
        # 높이 0.01*zh(400)=4px < 15px → 제거
        det = [{"label": "person", "bbox": [0.5, 0.5, 0.6, 0.51], "conf": 0.5}]
        self.assertEqual(zone_tile.zone_tile_detect(_frame(), ZONE, _stub(det), min_h_px=15), [])

    def test_degenerate_zone(self):
        self.assertEqual(zone_tile.zone_tile_detect(_frame(), [(0.1, 0.1)], _stub([])), [])
        self.assertEqual(zone_tile.zone_tile_detect(_frame(), [], _stub([])), [])


class TestFootInZone(unittest.TestCase):
    SQ = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

    def test_foot_inside(self):
        # 발(하단중앙) = (0.5, 0.5) 내부
        self.assertTrue(zone_tile.foot_in_zone([0.4, 0.3, 0.6, 0.5], self.SQ))

    def test_foot_outside(self):
        # 발 = (0.9, 0.5) 외부(x>0.8)
        self.assertFalse(zone_tile.foot_in_zone([0.85, 0.3, 0.95, 0.5], self.SQ))


if __name__ == "__main__":
    unittest.main()
