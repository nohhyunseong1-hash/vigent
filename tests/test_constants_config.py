"""[CODE_REVIEW M7-7(b)·R15] 하드코딩 상수 7개 → config/tuning.yaml 기본값 기재(읽기 경로 연결, 값 불변)
+ 카메라별 무동작 임계(motion.immobile_s) override 1키(등록부 overrides → 워커 → MotionTracker).

값은 코드 기본값과 같아 동작이 바뀌지 않는다(규칙 6). 이 테스트는 (1) 파일에 키가 있고 값이 코드 기본값과 같다
(2) 트래커·proximity 가 **파일값을 실제로 읽는다**(패치한 값이 반영) (3) 카메라별 override 가 등록부→워커→트래커로 흐른다 를 고정한다.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import camera_registry as reg  # noqa: E402
import proximity  # noqa: E402
import tuning  # noqa: E402
import worker  # noqa: E402

# (섹션, 키, 코드 기본값) — §2-3 표의 하드코딩 7개(10키)
_CONSTANTS = [
    ("motion", "match_dist", 0.32), ("motion", "immobile_spread", 0.03), ("motion", "immobile_min_samples", 5),
    ("motion", "rapid_window_s", 1.0), ("motion", "hist_s", 60.0), ("motion", "track_expire_s", 3.0),
    ("worker", "pose_match_dist", 0.18), ("worker", "pose_eval_min_s", 0.5),
    ("proximity", "vehicle_max_w", 0.9), ("proximity", "vehicle_max_area", 0.7),
]


class ConstantsInTuningYaml(unittest.TestCase):
    def test_yaml_has_keys_equal_to_code_defaults(self):
        with mock.patch.object(tuning, "_CACHE", None):
            for sec, key, default in _CONSTANTS:
                v = tuning.val(sec, key, None)
                self.assertIsNotNone(v, f"config/tuning.yaml 에 {sec}.{key} 가 없다")
                self.assertEqual(float(v), float(default), f"{sec}.{key} 는 코드 기본값과 같아야 한다(동작 불변)")

    def test_motion_tracker_reads_tuning_at_construction(self):
        cache = {"motion": {"match_dist": 0.5, "immobile_spread": 0.05, "immobile_min_samples": 3,
                            "rapid_window_s": 2.0, "hist_s": 30, "track_expire_s": 9, "immobile_s": 12}}
        with mock.patch.object(tuning, "_CACHE", cache):
            mt = worker.MotionTracker()
        self.assertEqual((mt.match, mt.immobile_spread, mt.immobile_min_samples, mt.rapid_t, mt.hist_s, mt.expire_s,
                          mt.immobile_s), (0.5, 0.05, 3, 2.0, 30.0, 9.0, 12.0))
        with mock.patch.object(tuning, "_CACHE", {}):
            d = worker.MotionTracker()
        self.assertEqual((d.match, d.immobile_spread, d.immobile_min_samples, d.rapid_t, d.hist_s, d.expire_s),
                         (0.32, 0.03, 5, 1.0, 60.0, 3.0))

    def test_ergonomics_tracker_reads_tuning_at_construction(self):
        with mock.patch.object(tuning, "_CACHE", {"worker": {"pose_match_dist": 0.4, "pose_eval_min_s": 0.9}}):
            et = worker.ErgonomicsTracker()
        self.assertEqual((et.match, et.min_interval), (0.4, 0.9))

    def test_proximity_size_filter_reads_tuning(self):
        with mock.patch.object(tuning, "_CACHE", None):
            self.assertEqual(proximity.vehicle_size_limits(), (0.9, 0.7))
        with mock.patch.object(tuning, "_CACHE", {"proximity": {"vehicle_max_w": 0.5, "vehicle_max_area": 0.3}}):
            self.assertEqual(proximity.vehicle_size_limits(), (0.5, 0.3))


class CameraImmobileOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for name, p in (("_PUB", d / "cameras.json"), ("_SEC", d / "camera_secrets.json")):
            pt = mock.patch.object(reg, name, p)
            pt.start()
            self.addCleanup(pt.stop)

    def test_tracker_accepts_camera_override(self):
        with mock.patch.object(tuning, "_CACHE", None):
            self.assertEqual(worker.MotionTracker().immobile_s, 45.0)
            self.assertEqual(worker.MotionTracker(immobile_s=90).immobile_s, 90.0)

    def test_registry_overrides_roundtrip_only_known_key(self):
        reg.upsert("c1", source="0", overrides={"motion": {"immobile_s": "90"}, "bogus": 1, "motion_x": {"a": 1}})
        self.assertEqual(reg.get("c1")["overrides"], {"motion": {"immobile_s": 90.0}})
        reg.upsert("c1", name="정문")                       # 다른 필드 수정은 overrides 를 보존
        self.assertEqual(reg.get("c1")["overrides"], {"motion": {"immobile_s": 90.0}})
        reg.upsert("c1", overrides={})                     # 빈 dict = 해제
        self.assertEqual(reg.get("c1").get("overrides"), {})
        with self.assertRaises(ValueError):
            reg.upsert("c1", overrides={"motion": {"immobile_s": -5}})

    def test_worker_setup_applies_override_and_exposes_it(self):
        import cv2
        import numpy as np
        png = Path(self.tmp.name) / "f.png"
        cv2.imwrite(str(png), np.zeros((16, 16, 3), dtype=np.uint8))
        w = worker.Worker()
        w._overrides = {"motion": {"immobile_s": 90}}
        with mock.patch.object(tuning, "_CACHE", None):
            out = w._setup_run(str(png), "t", 2.0, ["person"], None)
        ctx = out[1]
        self.assertEqual(ctx.mtrack.immobile_s, 90.0)
        self.assertEqual(w.state.get("immobile_s"), 90.0)   # /health·상태에 적용값이 보여야 한다(규칙 11)

    def test_manager_and_camera_start_thread_overrides(self):
        from routers import cameras as cams
        reg.upsert("c9", source="0", overrides={"motion": {"immobile_s": 77}})
        with mock.patch.object(worker.Worker, "start", return_value={"ok": True}) as ws:
            worker.manager.start(object(), object(), "c9", "0", name="c9", fps=2.0, overrides={"motion": {"immobile_s": 77}})
            self.assertEqual(ws.call_args.kwargs.get("overrides"), {"motion": {"immobile_s": 77}})
        worker.manager.remove("c9")
        with mock.patch.object(worker.manager, "start", return_value={"ok": True}) as ms, \
                mock.patch.object(cams, "_g2_register"), mock.patch.object(cams, "_guard", return_value=object()):
            cams._start("c9")
            self.assertEqual(ms.call_args.kwargs.get("overrides"), {"motion": {"immobile_s": 77.0}})


if __name__ == "__main__":
    unittest.main()
