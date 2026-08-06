"""worker zone-tile 통합 테스트 (B9 커밋②) — 기본 off, zone_intrusion 한정.

스텁 guard(구역 내 person 없음 → _derive zone_intrusion 미발화) + 스텁 rfdetr.detect_persons
(구역 내 person 반환)로, VIGENT_ZONE_TILE on/off 시 zone_intrusion 발화 여부를 검증.
RF-DETR 실로드 없음(detect_persons 를 스텁으로 대체).
"""
import os
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import data_engine  # noqa: E402
import rfdetr_service  # noqa: E402  (모듈 로드만 — 싱글톤 생성, 모델 로드 아님)
import worker  # noqa: E402

ZONE = [(0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95)]   # 거의 전체 프레임


def _ctx():
    mtrack = type("M", (), {"update": lambda s, d, t: []})()
    etrack = type("E", (), {"update": lambda s, f, t, b: []})()
    return worker._FrameCtx(["person"], ZONE, mtrack, etrack,
                            False, 30.0, ROOT / "data" / "x", "TZ", "test://src")


class _QuietGuard:
    """구역 내 person 없음 → _derive 는 zone_intrusion 을 발화하지 않는다."""
    def detect(self, frame, detectors=None, track_key="default"):
        return {"detections": [], "signals": {}, "person_count": 0}


class TestWorkerZoneTile(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.lock = threading.Lock()
        self.worker = worker.Worker()
        self.logged = []
        self._orig_log = data_engine.log_event
        data_engine.log_event = lambda **kw: self.logged.append(kw)
        # 타일 검출기 스텁(구역 내 person 1명) — RF-DETR 미로드
        self._orig_dp = rfdetr_service.rfdetr.detect_persons
        rfdetr_service.rfdetr.detect_persons = lambda img, thr=0.1: [
            {"label": "person", "bbox": [0.4, 0.4, 0.6, 0.9], "conf": 0.2}]

    def tearDown(self):
        data_engine.log_event = self._orig_log
        rfdetr_service.rfdetr.detect_persons = self._orig_dp
        os.environ.pop("VIGENT_ZONE_TILE", None)

    def test_on_fires_zone_intrusion_via_tile(self):
        os.environ["VIGENT_ZONE_TILE"] = "1"
        self.worker._process_frame(self.frame, 100.0, _QuietGuard(), self.lock, _ctx())
        rules = [k["rule"] for k in self.logged]
        self.assertIn("zone_intrusion", rules)

    def test_off_no_tile_fire(self):
        os.environ.pop("VIGENT_ZONE_TILE", None)
        self.worker._process_frame(self.frame, 100.0, _QuietGuard(), self.lock, _ctx())
        rules = [k["rule"] for k in self.logged]
        self.assertNotIn("zone_intrusion", rules)   # off 면 타일 회수 없음

    def test_no_double_fire_when_derive_already_fired(self):
        # guard 가 이미 구역 내 person 을 주면 _derive 가 발화 → 타일은 추가 발화 안 함(중복 금지)
        os.environ["VIGENT_ZONE_TILE"] = "1"

        class _ZoneGuard:
            def detect(self, frame, detectors=None, track_key="default"):
                return {"detections": [{"label": "person", "bbox": [0.4, 0.4, 0.6, 0.9], "conf": 0.9}],
                        "signals": {}, "person_count": 1}
        self.worker._process_frame(self.frame, 100.0, _ZoneGuard(), self.lock, _ctx())
        zi = [k for k in self.logged if k["rule"] == "zone_intrusion"]
        self.assertEqual(len(zi), 1)   # 한 번만


if __name__ == "__main__":
    unittest.main()
