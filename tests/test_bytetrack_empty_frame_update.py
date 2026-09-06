"""[CODE_REVIEW M1-5] ByteTrack — person 0건 프레임에서도 트래커 시간이 흘러야 한다.

배경(guard.py `_track_bytetrack` 주석·실측 2026-08-13): person 검출이 0건이면 `bt.update()` 를
호출하지 않고 early return 했다. 그러면 사람이 화면에 없는 동안 **트래커의 시간이 멈춰**
lost_track_buffer 가 만료되지 않고, 11.55초 부재 후에도 같은 tid 가 부활했다. tid 단위
쿨다운·구역 디바운스가 옛 사람에게 이어붙는 원인.

고정하는 계약:
  ① 트래커가 이미 있으면 person 0건 프레임에서도 update(빈 Detections) 를 호출한다(시간 진행)
  ② 트래커가 아직 없으면(그 키의 첫 프레임부터 사람이 없음) 굳이 만들지 않는다
  ③ person 이 있는 프레임의 동작(tid 오프셋 부여·타 클래스 _track_iou)은 그대로
"""
import sys
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import supervision  # noqa: E402,F401,I001  ★대역 설치 전에 미리 올린다 — sys.modules 복원 시 scipy 재import 사고 방지

import agents.guard as guard_mod  # noqa: E402


class _FakeBT:
    """update 호출을 기록하는 최소 ByteTrackTracker 대역."""

    instances: list = []

    def __init__(self, **kw):
        self.calls: list[int] = []          # 호출마다 입력 검출 수
        _FakeBT.instances.append(self)

    def update(self, det):
        self.calls.append(len(det))
        det.tracker_id = np.arange(len(det), dtype=int)
        return det


def _guard() -> guard_mod.GuardAgent:
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.TRACK_ALGO = "bytetrack"
    return g


def _person(x=0.1):
    return {"label": "person", "conf": 0.9, "bbox": [x, 0.1, x + 0.2, 0.6], "detector": "person"}


class ByteTrackEmptyFrame(unittest.TestCase):
    def setUp(self):
        _FakeBT.instances = []
        fake_mod = types.ModuleType("trackers")
        fake_mod.ByteTrackTracker = _FakeBT
        # ★mock.patch.dict(sys.modules) 는 복원 때 그 사이 import 된 모듈 전부를 지워 C확장(scipy) 재import
        #   오류를 낸다 — 'trackers' 키 하나만 바꾸고 되돌린다.
        self._saved = sys.modules.get("trackers")
        sys.modules["trackers"] = fake_mod

        def _restore():
            if self._saved is None:
                sys.modules.pop("trackers", None)
            else:
                sys.modules["trackers"] = self._saved
        self.addCleanup(_restore)

    def test_empty_frame_advances_existing_tracker(self):
        g = _guard()
        g._track_bytetrack([_person()], "k")            # 트래커 생성 + 사람 1명
        g._track_bytetrack([], "k")                     # ★사람 0명 — 시간이 흘러야 한다
        g._track_bytetrack([], "k")
        bt = _FakeBT.instances[0]
        self.assertEqual(bt.calls, [1, 0, 0], f"빈 프레임에서 update 가 호출되지 않았다: {bt.calls}")

    def test_empty_frame_without_tracker_creates_nothing(self):
        g = _guard()
        out = g._track_bytetrack([], "fresh")
        self.assertEqual(out, [])
        self.assertEqual(_FakeBT.instances, [], "사람이 한 번도 없던 키에 트래커를 만들 이유가 없다")
        self.assertNotIn("fresh", g._bytetrack_by_key)

    def test_person_frame_behaviour_unchanged(self):
        g = _guard()
        out = g._track_bytetrack([_person(), {"label": "forklift", "conf": 0.8,
                                              "bbox": [0.5, 0.5, 0.9, 0.9], "detector": "forklift"}], "k")
        persons = [d for d in out if d["label"] == "person"]
        others = [d for d in out if d["label"] != "person"]
        self.assertEqual(len(persons), 1)
        self.assertEqual(persons[0]["tid"], 0 + guard_mod._BYTETRACK_TID_OFFSET)   # 오프셋 그대로
        self.assertEqual(len(others), 1)                                          # 타 클래스는 _track_iou

    def test_empty_frame_returns_other_classes_tracked(self):
        g = _guard()
        g._track_bytetrack([_person()], "k")
        out = g._track_bytetrack([{"label": "forklift", "conf": 0.8, "bbox": [0.5, 0.5, 0.9, 0.9],
                                   "detector": "forklift"}], "k")
        self.assertEqual([d["label"] for d in out], ["forklift"])
        self.assertEqual(_FakeBT.instances[0].calls, [1, 0])


if __name__ == "__main__":
    unittest.main()
