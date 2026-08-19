"""[G5] 지게차 운전자 제외 테스트 — proximity + zone_intrusion 공유 판정.

배경: 학원 실습장은 지게차에 사람이 상시 탑승한다. 운영 person 슬롯이 탑승 운전자를
89.6% 프레임에서 검출(실측)하므로, 제외가 없으면 근접·구역 경보가 상시 오발화한다.

★핵심 계약 2개:
  1) 탑승자(포함률 >= 임계)는 그 장비와의 근접·구역 침입에서 제외된다.
  2) **하차로 박스가 분리되면 즉시 다시 센다** — 하차 직후가 협착 최고 위험이므로
     제외가 과하면 안 된다(프레임 단위 판정, 이월 상태 없음).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import proximity  # noqa: E402


def cfg(**kw):
    vals = {"radius_m": 3.0, "driver_containment": 0.65, **kw}
    return mock.patch.object(proximity.tuning, "val",
                             side_effect=lambda s, k, d, env=None: vals.get(k, d))


FORK = {"label": "forklift", "bbox": [0.40, 0.30, 0.80, 0.90]}          # 장비 박스
DRIVER = {"label": "person", "bbox": [0.55, 0.35, 0.65, 0.60]}          # 완전 포함(운전석)
WALKER = {"label": "person", "bbox": [0.05, 0.50, 0.12, 0.85]}          # 멀리 보행자
NEARBY = {"label": "person", "bbox": [0.82, 0.45, 0.90, 0.88]}          # 장비 바로 옆(비포함)
DISMOUNTED = {"label": "person", "bbox": [0.78, 0.45, 0.88, 0.88]}      # 하차 직후(소폭 겹침 ~20%)


class TestDriverExclusionInProximity(unittest.TestCase):
    def test_driver_fully_contained_is_excluded(self):
        """★탑승 운전자(포함률 1.0)는 거리 0 이어도 근접 쌍에서 제외된다."""
        with cfg():
            out = proximity.detect([FORK, DRIVER])
        self.assertEqual(out, [], "운전자가 근접 경보 쌍으로 잡혔다(상시 오발화 조건)")

    def test_nearby_pedestrian_still_fires(self):
        """장비 바로 옆(비포함) 보행자는 여전히 잡힌다 — 제외가 과하면 안 된다."""
        with cfg():
            out = proximity.detect([FORK, NEARBY])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["vehicle"], "forklift")

    def test_dismounted_person_counts_immediately(self):
        """★하차 직후(겹침 ~20% < 임계)는 즉시 보행자로 복귀 — 협착 최고 위험 순간."""
        with cfg():
            out = proximity.detect([FORK, DISMOUNTED])
        self.assertEqual(len(out), 1, "하차 직후 인물이 제외됐다(제외 과잉)")

    def test_mixed_scene_only_driver_excluded(self):
        """운전자+보행자 공존(실측 26s 장면): 보행자 쌍만 남는다."""
        near_walker = {"label": "person", "bbox": [0.20, 0.50, 0.30, 0.88]}
        with cfg(radius_m=100.0):                       # 거리 무관하게 쌍 형성
            out = proximity.detect([FORK, DRIVER, near_walker])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["person_bbox"], near_walker["bbox"])

    def test_disable_via_threshold_above_one(self):
        """롤백 경로: driver_containment > 1.0 이면 구 동작(운전자도 잡음)."""
        with cfg(driver_containment=1.5):
            out = proximity.detect([FORK, DRIVER])
        self.assertEqual(len(out), 1, "비활성인데 제외가 동작했다")

    def test_driver_still_paired_with_other_vehicle(self):
        """탑승 제외는 '그 장비와의 쌍'만 — 다른 장비가 접근하면 여전히 평가(보수적)."""
        # DRIVER 를 포함하는 트럭을 쓰면 둘 다 제외되므로, 운전자를 '부분만' 겹치게 배치
        drv = {"label": "person", "bbox": [0.42, 0.35, 0.50, 0.60]}     # FORK 에 완전 포함
        other2 = {"label": "truck", "bbox": [0.00, 0.30, 0.46, 0.95]}   # drv 포함률 0.5(<임계) — 쌍 유지돼야 함
        with cfg(radius_m=100.0):
            out = proximity.detect([FORK, other2, drv])
        vehicles = {o["vehicle"] for o in out}
        self.assertNotIn("forklift", vehicles, "탑승 장비와의 쌍이 제외되지 않았다")
        self.assertIn("truck", vehicles, "다른 장비와의 쌍까지 제외됐다(보수 원칙 위반)")


class TestOnboardHelperForZone(unittest.TestCase):
    """zone_intrusion 공유 헬퍼 — worker._eval_frame 이 이 함수로 운전자를 건너뛴다."""

    def test_onboard_true_for_driver(self):
        with cfg():
            self.assertTrue(proximity.onboard_vehicle(DRIVER["bbox"], [FORK, DRIVER]))

    def test_onboard_false_for_walker(self):
        with cfg():
            self.assertFalse(proximity.onboard_vehicle(WALKER["bbox"], [FORK, WALKER]))

    def test_onboard_false_without_vehicle(self):
        """장비 검출이 없으면 제외 없음 — 기존 동작 그대로."""
        with cfg():
            self.assertFalse(proximity.onboard_vehicle(DRIVER["bbox"], [DRIVER]))

    def test_onboard_false_when_disabled(self):
        with cfg(driver_containment=1.5):
            self.assertFalse(proximity.onboard_vehicle(DRIVER["bbox"], [FORK, DRIVER]))

    def test_dismount_transition_frame_level(self):
        """하차 시퀀스: 탑승 프레임 True → 분리 프레임 즉시 False(이월 상태 없음)."""
        with cfg():
            self.assertTrue(proximity.onboard_vehicle(DRIVER["bbox"], [FORK, DRIVER]))
            self.assertFalse(proximity.onboard_vehicle(DISMOUNTED["bbox"], [FORK, DISMOUNTED]))


class TestContainmentMath(unittest.TestCase):
    def test_full_containment(self):
        self.assertAlmostEqual(proximity._containment([0.5, 0.4, 0.6, 0.6], FORK["bbox"]), 1.0)

    def test_zero_containment(self):
        self.assertEqual(proximity._containment(WALKER["bbox"], FORK["bbox"]), 0.0)

    def test_partial(self):
        v = proximity._containment(DISMOUNTED["bbox"], FORK["bbox"])
        self.assertTrue(0.0 < v < 0.65, f"경계 픽스처가 임계를 넘었다: {v}")


if __name__ == "__main__":
    unittest.main()
