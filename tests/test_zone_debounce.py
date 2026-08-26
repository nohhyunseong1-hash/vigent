"""[B6] 위험구역 침입 시간 디바운스 테스트.

배경(감사 🔴B6): PPE(3프레임)·화재(2프레임)에는 히스테리시스가 있는데 **침입에는 없어서**
단일 프레임 오검출이 곧 경보였다. 파일럿의 유일한 판매 기능이 이것이다.

핵심 시나리오 3종(지시서):
  1. 1프레임 스침      → 미발화
  2. T초 체류          → 발화
  3. 경계 왕복         → 1회만 발화
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker  # noqa: E402
import zone_debounce  # noqa: E402


class TestRefPoint(unittest.TestCase):
    """판정 기준점 — 기본은 발끝(박스 하단 중앙), config 로 중심 선택 가능."""

    def test_foot_is_bottom_center(self):
        # bbox = x1,y1,x2,y2 (정규화)
        self.assertEqual(zone_debounce.ref_point([0.2, 0.1, 0.4, 0.9], "foot"), (0.30000000000000004, 0.9))

    def test_center_is_box_center(self):
        x, y = zone_debounce.ref_point([0.2, 0.1, 0.4, 0.9], "center")
        self.assertAlmostEqual(x, 0.3)
        self.assertAlmostEqual(y, 0.5)

    def test_default_matches_legacy_behavior(self):
        """기본값은 기존 코드와 동일해야 한다 — (x1+x2)/2, y2."""
        bbox = [0.1, 0.2, 0.5, 0.8]
        self.assertEqual(zone_debounce.ref_point(bbox), ((0.1 + 0.5) / 2, 0.8))


class TestDebouncer(unittest.TestCase):
    def setUp(self):
        self.d = zone_debounce.ZoneDebouncer()

    def test_single_frame_graze_does_not_fire(self):
        """★1프레임 스침 → 미발화. 이 테스트가 B6 의 존재 이유다."""
        t = 1000.0
        self.assertFalse(self.d.update("c1", False, t))
        self.assertFalse(self.d.update("c1", True, t + 0.4))    # 스침(0.4초)
        self.assertFalse(self.d.update("c1", False, t + 0.8))   # 바로 나감 → 확정 안 됨
        self.assertFalse(self.d.update("c1", False, t + 3.0))

    def test_dwell_fires_after_enter_s(self):
        """T초(기본 1.0) 체류 → 발화."""
        t = 2000.0
        self.d.update("c1", False, t)
        self.assertFalse(self.d.update("c1", True, t + 0.1))    # 진입 직후엔 아직
        self.assertFalse(self.d.update("c1", True, t + 0.9))    # 0.9초 — 아직
        self.assertTrue(self.d.update("c1", True, t + 1.2))     # 1.1초 유지 → 확정

    def test_boundary_oscillation_fires_once(self):
        """★경계 왕복 → 1회만 발화. exit 유예 덕에 확정 상태가 유지돼 재발화가 없다."""
        t = 3000.0
        self.d.update("c1", False, t)
        transitions = 0
        prev = False
        # 1.5초 체류 후, 0.3초 간격으로 경계를 8번 넘나든다
        seq = [(True, 0.5), (True, 1.6)] + [((i % 2 == 0), 1.9 + i * 0.3) for i in range(8)]
        for raw, dt in seq:
            now = self.d.update("c1", raw, t + dt)
            if now and not prev:
                transitions += 1
            prev = now
        self.assertEqual(transitions, 1, "경계 왕복 중 재발화가 발생했다")

    def test_exit_requires_sustained_absence(self):
        """이탈도 유예가 있어야 한다 — 잠깐 가려져 박스가 빠져도 즉시 해제되지 않는다."""
        t = 4000.0
        self.d.update("c1", False, t)
        self.d.update("c1", True, t + 0.1)
        self.assertTrue(self.d.update("c1", True, t + 1.5))     # 확정 진입
        self.assertTrue(self.d.update("c1", False, t + 1.8))    # 0.3초 사라짐 — 유지
        self.assertTrue(self.d.update("c1", False, t + 2.5))    # 0.7초 — 아직 유지
        self.assertFalse(self.d.update("c1", False, t + 3.0))   # 1.2초 → 이탈 확정

    def test_cameras_are_independent(self):
        t = 5000.0
        self.d.update("c1", False, t); self.d.update("c2", False, t)
        self.d.update("c1", True, t + 0.1)
        self.assertTrue(self.d.update("c1", True, t + 1.5))
        self.assertFalse(self.d.state("c2")["confirmed"])

    def test_starts_outside_even_if_person_present_at_boot(self):
        """기동 순간 구역 안에 사람이 있어도 유예 없이 발화하면 안 된다."""
        t = 6000.0
        self.assertFalse(self.d.update("c1", True, t))          # 첫 관측
        self.assertTrue(self.d.update("c1", True, t + 1.5))     # 정상 유예 후 확정


class TestDeriveIntegration(unittest.TestCase):
    """worker._derive 배선 — 디바운서를 통과해야 fired 가 나온다."""

    ZONE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]     # 전체 화면 구역
    OUT = {"detections": [{"label": "person", "bbox": [0.4, 0.4, 0.6, 0.8]}], "signals": {}}

    def _rules(self, fired):
        return [r for r, *_ in fired]

    def test_no_fire_on_single_frame(self):
        d = zone_debounce.ZoneDebouncer()
        fired = worker._derive(self.OUT, self.ZONE, None, cid="c1", debouncer=d)
        self.assertNotIn("zone_intrusion", self._rules(fired))

    def test_fires_after_dwell(self):
        d = zone_debounce.ZoneDebouncer()
        worker._derive(self.OUT, self.ZONE, None, cid="c1", debouncer=d)
        with mock.patch("time.time", return_value=__import__("time").time() + 2.0):
            fired = worker._derive(self.OUT, self.ZONE, None, cid="c1", debouncer=d)
        self.assertIn("zone_intrusion", self._rules(fired))

    def test_legacy_path_still_fires_immediately(self):
        """디바운서 미주입(하위호환) 경로는 기존대로 즉시 발화 — 기존 호출부 회귀 0."""
        fired = worker._derive(self.OUT, self.ZONE, None)
        self.assertIn("zone_intrusion", self._rules(fired))

    def test_person_outside_zone_never_fires(self):
        d = zone_debounce.ZoneDebouncer()
        zone = [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)]   # 좌상단 작은 구역
        for _ in range(5):
            fired = worker._derive(self.OUT, zone, None, cid="c1", debouncer=d)
            self.assertNotIn("zone_intrusion", self._rules(fired))


if __name__ == "__main__":
    unittest.main()
