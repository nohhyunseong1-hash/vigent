"""[CODE_REVIEW M2-1] 구역 침입 주체 키(t<tid>·g<x>_<y>)는 퇴장 확정 후 정리돼야 한다.

배경: worker._derive 는 구역 안에 들어온 주체를 `debouncer._vigent_seen`(known) 과 디바운서 `_st` 에
넣기만 하고 지우지 않았다. ByteTrack tid 는 단조 증가라 카메라가 켜져 있는 한 키가 무한히 쌓이고
매 프레임 전수 순회했다(루프 내 메모리 누적). 계약:
  ① 안에 있는(확정) 주체는 유지  ② 퇴장 확정(exit_s 경과) 주체는 known·_st 에서 제거
  ③ 장시간 시뮬레이션(주체 300명 순차 진입·퇴장)에서 키 수가 상수 상한 안에 머문다
  ④ 정리된 주체가 다시 들어오면 새 진입으로 발화한다(기존 동작)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker as W  # noqa: E402
import zone_debounce  # noqa: E402

ZONE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def _det(tid, inside=True):
    b = [0.4, 0.4, 0.6, 0.7] if inside else [0.90, 0.90, 0.99, 0.95]
    return {"label": "person", "conf": 0.9, "bbox": b, "tid": tid}


def _out(*dets):
    return {"detections": list(dets), "signals": {}, "person_count": len(dets)}


class ZoneSubjectPruning(unittest.TestCase):
    def setUp(self):
        self.db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)

    def _pump(self, *dets, n=2):
        got = []
        for _ in range(n):
            got += W._derive(_out(*dets), ZONE, None, cid="c1", debouncer=self.db)
        return got

    def _known(self):
        return set(getattr(self.db, "_vigent_seen", set()))

    def test_confirmed_subject_is_kept(self):
        self._pump(_det(1), n=3)
        self.assertIn("t1", self._known())
        self.assertIn("c1#t1", self.db._st)

    def test_left_subject_is_pruned(self):
        self._pump(_det(1), n=2)                       # 진입 확정
        self._pump(_det(1, inside=False), n=3)         # 구역 밖 → 퇴장 확정(exit 0s)
        self.assertNotIn("t1", self._known(), "퇴장 확정 후에도 known 에 남아 있다")
        self.assertNotIn("c1#t1", self.db._st, "퇴장 확정 후에도 디바운서 상태가 남아 있다")

    def test_vanished_subject_is_pruned(self):
        """화면에서 아예 사라진 사람(검출 0건)도 정리돼야 한다."""
        self._pump(_det(1), n=2)
        self._pump(n=3)                                # 아무도 없음
        self.assertNotIn("t1", self._known())

    def test_long_run_is_bounded(self):
        for tid in range(1, 301):                       # 300명이 차례로 들어왔다 나간다
            self._pump(_det(tid), n=2)
            self._pump(n=2)
        self.assertLessEqual(len(self._known()), 2, f"known 이 누적된다: {len(self._known())}")
        self.assertLessEqual(len(self.db._st), 2, f"디바운서 상태가 누적된다: {len(self.db._st)}")

    def test_pruned_subject_reentry_fires_again(self):
        f1 = self._pump(_det(1), n=2)
        self.assertEqual([s for r, _l, _n, s in f1 if r == "zone_intrusion"], ["t1"])
        self._pump(n=3)                                # 사라짐 → 정리
        f2 = self._pump(_det(1), n=2)                  # 같은 tid 재진입 = 새 진입
        self.assertEqual([s for r, _l, _n, s in f2 if r == "zone_intrusion"], ["t1"])


if __name__ == "__main__":
    unittest.main()
