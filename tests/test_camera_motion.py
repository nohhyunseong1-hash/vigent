"""[CODE_REVIEW M3-1] 카메라 흔들림(팬/틸트) 억제 — 다수 트랙 동시 이동이면 그 표본의 급격동작 판정을 억제.

대표 결정(b): 트랙 ≥2 이고 과반이 같은 표본에서 같은 방향(코사인 유사도 기준)으로 임계 이상 이동하면
급격동작을 억제하고 camera_motion 플래그를 남긴다. 고정 CCTV 전제(PTZ 도입 시 전역 이동 보정 필요 — 메모).
계약:
  ① 트랙 2개가 같은 방향으로 0.3 이동 → rapid_motion 없음, camera_motion=True
  ② 트랙 2개 중 1개만 이동 → 그 사람은 rapid_motion(억제 없음), camera_motion=False
  ③ 트랙 2개가 서로 반대 방향으로 이동 → 억제 없음(교차 보행)
  ④ 트랙 1개만 있을 때는 규칙 적용 불가 → 기존 동작(발화)
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


class CameraMotionSuppression(unittest.TestCase):
    def setUp(self):
        self.mt = W.MotionTracker()

    def _run(self, frames):
        out = []
        for ts, dets in frames:
            out = self.mt.update(dets, ts)
        return out

    def test_two_tracks_same_direction_is_camera_motion(self):
        out = self._run([(0.0, [_p(0.2, tid=1), _p(0.6, tid=2)]),
                         (0.5, [_p(0.35, tid=1), _p(0.75, tid=2)]),
                         (1.0, [_p(0.5, tid=1), _p(0.9, tid=2)])])       # 둘 다 +0.30 같은 방향
        self.assertNotIn("rapid_motion", _rules(out), "카메라 팬(전 트랙 동시 이동)을 급격동작으로 발화했다")
        self.assertTrue(self.mt.camera_motion)

    def test_only_one_of_two_moves_fires(self):
        out = self._run([(0.0, [_p(0.2, tid=1), _p(0.6, tid=2)]),
                         (0.5, [_p(0.35, tid=1), _p(0.6, tid=2)]),
                         (1.0, [_p(0.5, tid=1), _p(0.6, tid=2)])])       # 1만 이동
        self.assertIn("rapid_motion", _rules(out))
        self.assertFalse(self.mt.camera_motion)

    def test_opposite_directions_fire(self):
        out = self._run([(0.0, [_p(0.2, tid=1), _p(0.8, tid=2)]),
                         (0.5, [_p(0.35, tid=1), _p(0.65, tid=2)]),
                         (1.0, [_p(0.5, tid=1), _p(0.5, tid=2)])])       # 서로 마주 달림
        self.assertIn("rapid_motion", _rules(out))
        self.assertFalse(self.mt.camera_motion)

    def test_single_track_unchanged(self):
        out = self._run([(0.0, [_p(0.2, tid=1)]), (0.5, [_p(0.35, tid=1)]), (1.0, [_p(0.5, tid=1)])])
        self.assertIn("rapid_motion", _rules(out))
        self.assertFalse(self.mt.camera_motion)

    def test_three_tracks_majority_rule(self):
        """3개 중 2개(과반)가 같은 방향 → 억제. 1개만 반대라도 카메라 이동으로 본다."""
        out = self._run([(0.0, [_p(0.2, tid=1), _p(0.5, tid=2), _p(0.8, tid=3)]),
                         (0.5, [_p(0.35, tid=1), _p(0.65, tid=2), _p(0.8, tid=3)]),
                         (1.0, [_p(0.5, tid=1), _p(0.8, tid=2), _p(0.8, tid=3)])])
        self.assertNotIn("rapid_motion", _rules(out))
        self.assertTrue(self.mt.camera_motion)


if __name__ == "__main__":
    unittest.main()
