"""[CODE_REVIEW M2-2·M2-3·M2-8] 급격동작·무동작·군집 규칙 단위 테스트(정상 발화 1 + 억제 1 이상).

M2-2: MotionTracker 는 guard 가 주는 안정 tid 를 **우선** 사용하고, tid 가 없을 때만 중심점 매칭으로
  폴백한다. 예전엔 tid 를 무시하고 중심점 최근접(0.32=화면 폭 1/3)만 써서, 한 사람이 나가고 옆에
  다른 사람이 나타나면 "같은 사람이 0.25 이동" 으로 붙어 급격동작이 오발화했다.
M2-3: 급격동작 거리에 y 스케일 보정(aspect_hw=h/w) — 협착(proximity._gap)과 같은 방식.
M2-8: 급격동작·무동작·군집 각각 정상 발화 + 억제 케이스.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker as W  # noqa: E402


def _p(x, y=0.5, tid=None, w=0.1, h=0.3):
    d = {"label": "person", "conf": 0.9, "bbox": [x - w / 2, y - h / 2, x + w / 2, y + h / 2]}
    if tid is not None:
        d["tid"] = tid
    return d


def _rules(fired):
    return [r for r, *_ in fired]


class RapidMotion(unittest.TestCase):
    def setUp(self):
        self.mt = W.MotionTracker()
        self.assertEqual(self.mt.RAPID_DIST, 0.15, "테스트가 가정하는 임계와 다름")
        self.assertEqual(self.mt.RAPID_T, 1.0)

    def test_same_tid_moving_far_fires(self):
        self.mt.update([_p(0.20, tid=1)], 0.0)
        self.mt.update([_p(0.30, tid=1)], 0.5)
        out = self.mt.update([_p(0.50, tid=1)], 1.0)       # 1.0s 창 안에서 0.30 이동
        self.assertIn("rapid_motion", _rules(out))

    def test_same_tid_walking_slowly_is_suppressed(self):
        self.mt.update([_p(0.20, tid=1)], 0.0)
        self.mt.update([_p(0.25, tid=1)], 0.5)
        out = self.mt.update([_p(0.30, tid=1)], 1.0)       # 0.10 < 0.15
        self.assertNotIn("rapid_motion", _rules(out))

    def test_new_person_nearby_is_not_fake_rapid(self):
        """★M2-2 핵심 — A(tid1)가 사라지고 B(tid2)가 0.25 옆에 나타난 것은 이동이 아니다."""
        self.mt.update([_p(0.20, tid=1)], 0.0)
        self.mt.update([_p(0.20, tid=1)], 0.5)
        out = self.mt.update([_p(0.45, tid=2)], 1.0)
        self.assertNotIn("rapid_motion", _rules(out),
                         "다른 tid 를 같은 사람으로 이어붙여 급격동작을 오발화했다")

    def test_tid_jump_beyond_limit_is_new_track(self):
        """★ByteTrack ID 재부여 방어(육안검증 multi_scene 19.0·19.5s): 같은 tid 가 한 표본에 0.3 점프하면 '다른 사람'."""
        self.assertEqual(self.mt.TID_JUMP_MAX, 0.25)
        self.mt.update([_p(0.20, tid=1)], 0.0)
        self.mt.update([_p(0.20, tid=1)], 0.5)
        out = self.mt.update([_p(0.50, tid=1)], 1.0)       # 0.30 ≥ 0.25 → 새 트랙(재부여로 판단)
        self.assertNotIn("rapid_motion", _rules(out),
                         "tid 점프(ID 재부여)를 실제 이동으로 보고 급격동작을 오발화했다")

    def test_tid_jump_gate_uses_scaled_distance(self):
        """게이트 거리도 y×(h/w) 보정 — 세로형(h/w=1.78)에서 y 0.16 점프는 0.28 로 재부여다."""
        self.mt.update([_p(0.5, 0.30, tid=1)], 0.0, aspect_hw=1.78)
        self.mt.update([_p(0.5, 0.30, tid=1)], 0.5, aspect_hw=1.78)
        out = self.mt.update([_p(0.5, 0.46, tid=1)], 1.0, aspect_hw=1.78)
        self.assertNotIn("rapid_motion", _rules(out))

    def test_window_tolerates_15fps_cadence(self):
        """15fps 를 2fps 표본화하면 간격 0.533s → 두 표본 1.067s. 창(1.0s)에 여유가 없으면 실제 횡단을 놓친다
        (육안검증: single_fast 5.85s·occlusion 10.13s 실제 이동을 신 동작이 놓쳤다)."""
        self.mt.update([_p(0.20, tid=1)], 0.000)
        self.mt.update([_p(0.32, tid=1)], 0.533)
        out = self.mt.update([_p(0.44, tid=1)], 1.067)     # 총 0.24 > 0.15, 창 1.067 ≤ 1.0+0.1
        self.assertIn("rapid_motion", _rules(out))

    def test_centroid_fallback_without_tid(self):
        """tid 가 없으면(추적 미확정·passthrough) 기존 중심점 매칭으로 동작한다."""
        self.mt.update([_p(0.20)], 0.0)
        self.mt.update([_p(0.30)], 0.5)
        out = self.mt.update([_p(0.50)], 1.0)
        self.assertIn("rapid_motion", _rules(out))

    def test_vertical_move_is_scaled_by_aspect(self):
        """M2-3 — 16:9 프레임에서 y 0.20 이동은 x 척도로 0.1125 (< 0.15) 라 급격동작이 아니다."""
        self.mt.update([_p(0.5, 0.30, tid=1)], 0.0, aspect_hw=9 / 16)
        self.mt.update([_p(0.5, 0.40, tid=1)], 0.5, aspect_hw=9 / 16)
        out = self.mt.update([_p(0.5, 0.50, tid=1)], 1.0, aspect_hw=9 / 16)
        self.assertNotIn("rapid_motion", _rules(out))
        # 보정 없이(정사각 가정)는 0.20 > 0.15 → 발화(기존 동작 = 폴백)
        mt2 = W.MotionTracker()
        mt2.update([_p(0.5, 0.30, tid=1)], 0.0)
        mt2.update([_p(0.5, 0.40, tid=1)], 0.5)
        self.assertIn("rapid_motion", _rules(mt2.update([_p(0.5, 0.50, tid=1)], 1.0)))


class Immobility(unittest.TestCase):
    def setUp(self):
        self.mt = W.MotionTracker()
        self.assertEqual(self.mt.IMMOBILE_S, 45.0, "테스트가 가정하는 임계와 다름")

    def _feed(self, seconds, jitter=0.0, tid=1):
        out = []
        t = 0.0
        i = 0
        while t <= seconds:
            dx = jitter if i % 2 else 0.0
            out = self.mt.update([_p(0.5 + dx, 0.5, tid=tid)], t)
            t += 0.5
            i += 1
        return out

    def test_still_person_fires_after_threshold(self):
        out = self._feed(46.0)
        self.assertIn("immobility", _rules(out))

    def test_young_track_does_not_fire(self):
        out = self._feed(30.0)
        self.assertNotIn("immobility", _rules(out))

    def test_moving_person_does_not_fire(self):
        out = self._feed(46.0, jitter=0.05)             # 퍼짐 0.05 > 0.03
        self.assertNotIn("immobility", _rules(out))


class CrowdDensity(unittest.TestCase):
    def _out(self, n):
        dets = [_p(0.1 + 0.12 * i, tid=i) for i in range(n)]
        return {"detections": dets, "signals": {}, "person_count": n}

    def test_six_people_fire(self):
        import tuning
        thr = int(tuning.val("crowd", "threshold", 6))
        fired = W._derive(self._out(thr), [], None)
        self.assertIn("crowd_density", _rules(fired))

    def test_below_threshold_is_suppressed(self):
        import tuning
        thr = int(tuning.val("crowd", "threshold", 6))
        fired = W._derive(self._out(thr - 1), [], None)
        self.assertNotIn("crowd_density", _rules(fired))


if __name__ == "__main__":
    unittest.main()
