"""[B-passthru] 검출통과 + 위치 기반 대체 키 — **기본 off** 이고, 켜도 안전한가.

★배경(2026-08-25 실측): ByteTrack 이 검출의 29.3%p 를 버린다(검출 71.3% → 추적후 42.0%,
원거리는 83%→8%). 그런데 [D1-C] 가 구역 판정 키로 tid 를 쓰기 때문에, 추적이 버린 검출
(tid 없음)은 판정에서 통째로 빠졌다 — **되살려도 경보에 닿지 않았다**(실측: 99건 전부 무시).

여기서 고정하는 계약:
  1) ★**둘 다 기본 off** — 승인 전에는 동작이 조금도 바뀌지 않는다(규칙6).
  2) 검출통과는 **이미 추적된 사람과 겹치는 박스를 버린다** — 중복 제거가 없으면
     같은 사람에 박스가 둘이 되어 곧바로 오탐이 된다(실측: 정밀도 82.5→54.2% 붕괴).
  3) 위치 기반 키는 **같은 자리면 같은 키, 다른 자리면 다른 키**여야 한다.
  4) tid 가 있는 검출은 **여전히 tid 키를 쓴다**(D1-C 유지).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import vision_loader  # noqa: E402
import worker as W  # noqa: E402
import zone_debounce  # noqa: E402
from agents.guard import GuardAgent  # noqa: E402

ZONE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def _det(bbox, tid=None, conf=0.9):
    d = {"label": "person", "conf": conf, "bbox": bbox}
    if tid is not None:
        d["tid"] = tid
    return d


def _out(*dets):
    return {"detections": list(dets), "signals": {}, "person_count": len(dets)}


class DefaultsAreOff(unittest.TestCase):
    """계약 1 — ★승인 전에는 아무것도 바뀌지 않는다."""

    def test_passthrough_off_by_default(self):
        g = GuardAgent(vision_loader.load_vision("safety"))
        self.assertEqual(g.PASSTHROUGH_CONF, 0.0,
                         "★검출통과가 기본으로 켜졌다 — 승인 없이 동작이 바뀐다")

    def test_grid_off_by_default(self):
        self.assertEqual(W._grid_cells(), 0,
                         "★위치 기반 키가 기본으로 켜졌다 — 승인 없이 판정이 바뀐다")

    def test_grid_off_means_tidless_ignored_when_tracks_exist(self):
        """★off 면 기존 동작 그대로 — **트랙이 있을 때** tid 없는 검출은 판정에서 빠진다.

        이게 B-passthru 가 메우려는 구멍이다(실측: 되살린 99건 전부 무시, 경보 변화 0).
        ※트랙이 **하나도 없으면** 카메라 단위 폴백이 발화한다 — 그건 D1-C 하위호환 경로로,
          여기서 검사하는 구멍과 다른 상황이다.
        """
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        subs = []
        for _ in range(4):     # 추적된 사람(t1) + tid 없는 사람이 함께 있는 장면
            for r, _lv, _n, s in W._derive(
                    _out(_det([0.30, 0.30, 0.40, 0.45], tid=1), _det([0.60, 0.60, 0.70, 0.75])),
                    ZONE, None, cid="c", debouncer=db):
                if r == "zone_intrusion":
                    subs.append(s)
        self.assertEqual(subs, ["t1"],
                         f"off 인데 tid 없는 검출이 판정에 들어왔다: {subs}")

    def test_grid_on_covers_that_gap(self):
        """★켜면 그 구멍이 메워진다 — 같은 장면에서 tid 없는 사람도 잡힌다."""
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        subs = []
        with mock.patch.object(W, "_grid_cells", lambda: 20):
            for _ in range(4):
                for r, _lv, _n, s in W._derive(
                        _out(_det([0.30, 0.30, 0.40, 0.45], tid=1), _det([0.60, 0.60, 0.70, 0.75])),
                        ZONE, None, cid="c", debouncer=db):
                    if r == "zone_intrusion":
                        subs.append(s)
        self.assertIn("t1", subs, "추적된 사람이 사라졌다")
        self.assertTrue(any(s.startswith("g") for s in subs),
                        f"★tid 없는 사람이 여전히 무시된다: {subs}")


class GridKeyBehaviour(unittest.TestCase):
    """계약 3·4 — 켰을 때의 키 동작."""

    def test_same_place_same_key(self):
        """★같은 자리에 머무는 대상은 같은 키 → 디바운스·쿨다운이 정상 작동한다."""
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        with mock.patch.object(W, "_grid_cells", lambda: 20):
            subs = []
            for _ in range(4):
                for r, _lv, _n, s in W._derive(_out(_det([0.4, 0.4, 0.6, 0.7])),
                                               ZONE, None, cid="c", debouncer=db):
                    if r == "zone_intrusion":
                        subs.append(s)
        self.assertEqual(len(subs), 1, f"같은 자리인데 {len(subs)}회 발화 — 키가 흔들린다")
        self.assertTrue(subs[0].startswith("g"), f"위치 키가 아니다: {subs[0]}")

    def test_different_place_different_key(self):
        """다른 자리의 진입은 새 키 → 두 번째 사람이 가려지지 않는다."""
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        with mock.patch.object(W, "_grid_cells", lambda: 20):
            subs = []
            for boxes in ([_det([0.30, 0.30, 0.40, 0.45])],
                          [_det([0.30, 0.30, 0.40, 0.45])],
                          [_det([0.30, 0.30, 0.40, 0.45]), _det([0.60, 0.60, 0.70, 0.75])],
                          [_det([0.30, 0.30, 0.40, 0.45]), _det([0.60, 0.60, 0.70, 0.75])]):
                for r, _lv, _n, s in W._derive(_out(*boxes), ZONE, None, cid="c", debouncer=db):
                    if r == "zone_intrusion":
                        subs.append(s)
        self.assertEqual(len(set(subs)), 2, f"서로 다른 자리인데 키가 {set(subs)} — 구분 실패")

    def test_tid_still_wins(self):
        """계약 4 — tid 가 있으면 위치 키가 아니라 **tid 키**를 쓴다(D1-C 유지)."""
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        with mock.patch.object(W, "_grid_cells", lambda: 20):
            subs = []
            for _ in range(3):
                for r, _lv, _n, s in W._derive(_out(_det([0.4, 0.4, 0.6, 0.7], tid=7)),
                                               ZONE, None, cid="c", debouncer=db):
                    if r == "zone_intrusion":
                        subs.append(s)
        self.assertEqual(subs, ["t7"], f"tid 가 있는데 위치 키를 썼다: {subs}")


class PassthroughDedup(unittest.TestCase):
    """계약 2 — ★중복 제거가 살아 있는가(없으면 정밀도가 무너진다)."""

    def test_dedup_code_is_present(self):
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "agents"
               / "guard.py").read_text(encoding="utf-8")
        self.assertIn("if any(_iou(bb, e) >= self.TRACK_IOU for e in live):", src,
                      "★검출통과의 중복 제거가 사라졌다 — 같은 사람에 박스가 둘이 되어 오탐이 된다")
        self.assertIn('"passthrough": True', src, "되살린 박스 표시가 없다(사후 구분 불가)")

    def test_passthrough_boxes_have_no_tid(self):
        """되살린 박스는 tid 가 없어야 한다 — 있으면 가짜 ID 로 D1-C 를 오염시킨다."""
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "agents"
               / "guard.py").read_text(encoding="utf-8")
        self.assertIn('{**d, "tid": None, "passthrough": True}', src)


if __name__ == "__main__":
    unittest.main()
