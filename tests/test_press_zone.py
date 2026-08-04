"""2.6 프레스 방호구역 부위별 판정(press_zone.evaluate) 회귀.

손/팔뚝만 진입=무경보, 머리·어깨·몸통·하체 진입=위반, 상완 선분 교차=위반, 다인 개별 판정.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import press_zone  # noqa: E402

W, H = 640.0, 360.0
ZONE = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]   # 중앙 정사각(정규화)
OUT = (0.05 * W, 0.05 * H)      # 구역 밖 기본점(픽셀)
IN = (0.5 * W, 0.5 * H)         # 구역 안 중앙(픽셀)


def _pose(overrides, pid=0):
    """17 keypoint 기본 밖, overrides={idx:(px,py)} 만 이동. conf 전부 1.0."""
    kp = [list(OUT) for _ in range(17)]
    for i, xy in overrides.items():
        kp[i] = list(xy)
    return {"id": pid, "keypoints": kp, "keypoint_confidence": [1.0] * 17}


class TestPressZone(unittest.TestCase):
    def test_hand_only_no_alert(self):
        # 손목(9)·손 = 허용 부위 → 구역 안이어도 위반 아님
        out = press_zone.evaluate([_pose({9: IN})], [ZONE], W, H)
        self.assertEqual(out, [])

    def test_head_in_zone_violates(self):
        out = press_zone.evaluate([_pose({0: IN})], [ZONE], W, H)   # 코(0)=머리
        self.assertEqual(len(out), 1)
        self.assertIn("머리", out[0]["parts"])

    def test_lower_body_violates(self):
        out = press_zone.evaluate([_pose({15: IN})], [ZONE], W, H)  # 발목(15)=하체
        self.assertIn("하체", out[0]["parts"])

    def test_upper_arm_segment_crossing(self):
        # 어깨(5)·팔꿈치(7) 둘 다 구역 밖이나 상완 선분이 구역을 관통 → 위반(머리 숙임 대비)
        pose = _pose({5: (0.3 * W, 0.5 * H), 7: (0.7 * W, 0.5 * H)})
        out = press_zone.evaluate([pose], [ZONE], W, H)
        self.assertTrue(out and "어깨" in out[0]["parts"])

    def test_low_conf_ignored(self):
        pose = _pose({0: IN})
        pose["keypoint_confidence"][0] = 0.2   # conf < 0.5 → 무시
        self.assertEqual(press_zone.evaluate([pose], [ZONE], W, H), [])

    def test_multi_person_individual(self):
        a = _pose({9: IN}, pid=1)      # 손만 → 무경보
        b = _pose({0: IN}, pid=2)      # 머리 → 위반
        out = press_zone.evaluate([a, b], [ZONE], W, H)
        self.assertEqual([o["id"] for o in out], [2])

    def test_no_zone_no_alert(self):
        self.assertEqual(press_zone.evaluate([_pose({0: IN})], [], W, H), [])


if __name__ == "__main__":
    unittest.main()
