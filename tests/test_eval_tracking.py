"""[P2b] 추적 평가 지표 산출 로직 테스트.

GT 라벨이 없어 프록시 지표를 쓰므로, **지표 계산이 의도대로 되는지**를 합성 데이터로 검증한다
(영상 추론 없이 순수 계산만 — GPU 불필요).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval_tracking as et  # noqa: E402


def _f(idx, tracks):
    """tracks: [(tid, x1)] — 세로는 고정, 가로 위치만 준다."""
    return {"idx": idx, "tracks": [{"tid": t, "box": [x, 100.0, x + 60, 300.0]}
                                   for t, x in tracks]}


class TestIou(unittest.TestCase):
    def test_identical_is_one(self):
        b = [0.0, 0.0, 10.0, 10.0]
        self.assertAlmostEqual(et._iou(b, b), 1.0)

    def test_disjoint_is_zero(self):
        self.assertEqual(et._iou([0, 0, 10, 10], [100, 100, 110, 110]), 0.0)


class TestMetrics(unittest.TestCase):
    def test_stable_track_has_no_switch(self):
        """같은 id 가 계속 같은 자리 → ID 스위치 0."""
        frames = [_f(i, [(1, 100.0 + i)]) for i in range(10)]
        m = et.evaluate(frames)
        self.assertEqual(m["id_switches"], 0)
        self.assertEqual(m["unique_tids"], 1)

    def test_id_change_in_place_counts_as_switch(self):
        """★같은 위치인데 id 가 바뀌면 스위치로 센다."""
        frames = [_f(0, [(1, 100.0)]), _f(1, [(2, 101.0)])]
        m = et.evaluate(frames)
        self.assertEqual(m["id_switches"], 1)

    def test_reid_counted_when_same_id_returns(self):
        """공백 후 **같은 id** 로 복귀 → 재식별 성공."""
        frames = [_f(0, [(1, 100.0)]), _f(1, []), _f(2, []), _f(3, [(1, 100.0)])]
        m = et.evaluate(frames)
        self.assertEqual(m["reid_ok"], 1)
        self.assertEqual(m["reid_rate"], 100.0)

    def test_fragment_counted_when_other_id_takes_place(self):
        """사라진 자리에 **다른 id** 가 들어오면 단절로 센다."""
        frames = [_f(0, [(1, 100.0)]), _f(1, [(2, 100.0)])]
        m = et.evaluate(frames)
        self.assertEqual(m["fragmented"], 1)

    def test_reid_rate_none_when_no_events(self):
        """재식별·단절이 모두 0이면 비율은 None(0%로 오해하지 않게)."""
        frames = [_f(i, [(1, 100.0)]) for i in range(3)]
        self.assertIsNone(et.evaluate(frames)["reid_rate"])

    def test_person_counts(self):
        frames = [_f(0, [(1, 100.0), (2, 300.0)]), _f(1, [(1, 101.0)])]
        m = et.evaluate(frames)
        self.assertEqual(m["max_persons"], 2)
        self.assertEqual(m["avg_persons"], 1.5)
        self.assertEqual(m["unique_tids"], 2)

    def test_empty_frames_do_not_crash(self):
        m = et.evaluate([_f(0, []), _f(1, [])])
        self.assertEqual(m["unique_tids"], 0)
        self.assertEqual(m["avg_persons"], 0)


if __name__ == "__main__":
    unittest.main()
