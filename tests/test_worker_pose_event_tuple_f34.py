"""[F-34] 포즈 스레드의 ergonomic_risk 3-튜플이 섞여도 같은 프레임의 다른 경보가 기록 단계까지 도달해야 한다.

결함(2026-08-24 aa4df83 ~ 2026-09-10): ErgonomicsTracker.update 는 (rule, level, note) 3-튜플을 내고 _process_frame 의
쿨다운·기록 루프는 4-튜플(subject 포함)을 언패킹했다 → ValueError → 프레임 단위 except 가 삼켜 **그 프레임의 모든 경보**
(zone_intrusion·ppe_missing·fire_smoke·proximity·immobility)가 log_event·통보 큐에 도달하지 못했다.

검증 3가지:
  ① 3-튜플 포즈 이벤트 + fire_smoke 가 같은 프레임 → 둘 다 log_event 도달, state["frame_errors"] 없음
  ② 프레임 예외는 삼키되 state["frame_errors"] 카운터(frames·alerts·last_error·last_at)가 오르고 /health 합산 헬퍼가 그것을 모은다
  ③ 근골격 규칙을 설정으로 끈 상태(joints 없음 → ErgonomicsTracker 비활성)에서도 MotionTracker 의 immobility(쓰러짐 의심)는 기록된다
"""
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import data_engine  # noqa: E402
import worker  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


def _ctx(mtrack=None, etrack=None):
    mtrack = mtrack or type("M", (), {"update": lambda self, d, t: []})()
    etrack = etrack or type("E", (), {"update": lambda self, f, t, b: []})()
    return worker._FrameCtx(["person"], [], mtrack, etrack, False, 30.0,
                            ROOT / "data" / "dataset" / "images", "TESTCAM_F34", "test://src")


class _FireGuard:
    def detect(self, frame, detectors=None, track_key="default"):
        return {"signals": {"fire_smoke": True}, "detections": [], "person_count": 0}


class _QuietGuard:
    def detect(self, frame, detectors=None, track_key="default"):
        return {"signals": {}, "detections": [], "person_count": 0}


class _RaisingGuard:
    def detect(self, frame, detectors=None, track_key="default"):
        raise RuntimeError("boom-f34")


class TestPoseEventTupleF34(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.lock = threading.Lock()
        self.worker = worker.Worker()
        self._orig_log = data_engine.log_event
        self.logged = []
        data_engine.log_event = lambda **kw: self.logged.append(kw)

    def tearDown(self):
        data_engine.log_event = self._orig_log

    def test_pose_3tuple_does_not_drop_other_alerts(self):
        ctx = _ctx()
        # 포즈 스레드가 넘긴 산출물(3-튜플)을 그대로 주입 — 결함 재현 조건
        self.worker._pose_events = [("ergonomic_risk", "low", "허리 굽힘 · 4초 지속 · 등급 warn")]
        self.worker._process_frame(self.frame, 100.0, _FireGuard(), self.lock, ctx)
        rules = [e["rule"] for e in self.logged]
        self.assertIn("fire_smoke", rules, "포즈 3-튜플 때문에 화재 경보가 버려지면 안 된다(F-34)")
        self.assertIn("ergonomic_risk", rules, "포즈 이벤트 자체도 기록돼야 한다")
        self.assertNotIn("frame_errors", self.worker.state, "프레임 예외가 없어야 한다")
        self.assertEqual(self.worker.state["events"], 2)

    def test_pose_4tuple_passthrough(self):
        ctx = _ctx()
        self.worker._pose_events = [("ergonomic_risk", "low", "note", "")]   # 이미 4-튜플이면 그대로
        self.worker._process_frame(self.frame, 100.0, _QuietGuard(), self.lock, ctx)
        self.assertEqual([e["rule"] for e in self.logged], ["ergonomic_risk"])

    def test_frame_error_counter_and_health_aggregate(self):
        ctx = _ctx()
        self.worker._process_frame(self.frame, 100.0, _RaisingGuard(), self.lock, ctx)
        fe = self.worker.state.get("frame_errors")
        self.assertIsNotNone(fe, "삼킨 예외가 카운터로 보여야 한다")
        self.assertEqual(fe["frames"], 1)
        self.assertEqual(fe["alerts"], 0, "발화 전에 죽었으니 버려진 경보 0")
        self.assertIn("boom-f34", fe["last_error"])
        self.assertTrue(fe["last_at"])
        self.worker._process_frame(self.frame, 101.0, _RaisingGuard(), self.lock, ctx)
        self.assertEqual(self.worker.state["frame_errors"]["frames"], 2)
        # /health 합산 헬퍼(routers/system._dropped_by_error) — 카메라 2대 합산·최신 오류 1개
        from routers import system as _system
        agg = _system._dropped_by_error({"cameras": {
            "camA": {"frame_errors": {"frames": 2, "alerts": 3, "last_error": "frame: X: D:\\a\\b\\c.py", "last_at": "2026-09-10T01:00:00"}},
            "camB": {"frame_errors": {"frames": 1, "alerts": 0, "last_error": "frame: Y", "last_at": "2026-09-10T02:00:00"}},
            "camC": {}}})
        self.assertEqual((agg["frames"], agg["alerts"]), (3, 3))
        self.assertEqual(agg["cameras"], {"camA": 2, "camB": 1})
        self.assertEqual(agg["last_error"], "frame: Y")
        self.assertEqual(agg["last_at"], "2026-09-10T02:00:00")

    def test_ergonomics_off_by_config_keeps_immobility(self):
        # ① joints 가 없는 설정 → ErgonomicsTracker 는 비활성(update → [])  — 설정만으로 끄는 경로
        import ergonomics as _erg
        orig = _erg.load_ergonomics
        _erg.load_ergonomics = lambda theme="safety": {"framework": "REBA", "hold_sec": 3}   # joints 없음
        try:
            et = worker.ErgonomicsTracker()
        finally:
            _erg.load_ergonomics = orig
        self.assertFalse(et._enabled)
        self.assertEqual(et.update(self.frame, 100.0, []), [])
        # ② 같은 조건에서 MotionTracker 가 낸 immobility(3-튜플)는 그대로 기록된다 — 낙상 대체 규칙은 포즈와 무관
        mtrack = type("M", (), {"update": lambda self, d, t: [("immobility", "high", "장시간 무동작 — 쓰러짐·실신 의심")]})()
        ctx = _ctx(mtrack=mtrack, etrack=et)
        self.worker._process_frame(self.frame, 100.0, _QuietGuard(), self.lock, ctx)
        self.assertEqual([e["rule"] for e in self.logged], ["immobility"])
        self.assertNotIn("frame_errors", self.worker.state)


if __name__ == "__main__":
    unittest.main()
