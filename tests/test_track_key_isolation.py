"""track_key 격리(5단계·3.6 회귀방지): 서로 다른 track_key 로 다른 장면을 교대 추적해도
_tracks_by_key 가 섞이지 않음(유령박스 0). 3.6(허브 스포트라이트 track_key 누락→browser 풀 공유)
재발 방지. 모델 로드 없이 Guard._track 만 검증(__new__ + 클래스 기본 속성)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402


def _box(x1, y1, x2, y2, label="person"):
    return {"label": label, "bbox": [x1, y1, x2, y2], "conf": 0.9, "detector": "person"}


class TrackKeyIsolation(unittest.TestCase):
    def _guard(self):
        g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)   # __init__ 우회(모델·설정 로드 없이 _track 만)
        g._tracks_by_key = {}
        g._bytetrack_by_key = {}
        g._key_last_used = {}   # F-2: TTL 청소 상태(이 테스트는 스윕 트리거 안 걸리게 짧은 시퀀스만 씀)
        g._last_sweep_at = 0.0
        g._tid_seq = 0
        return g

    def test_two_keys_do_not_cross_contaminate(self):
        """고유 track_key 2개로 좌상단/우하단 장면을 교대 → 각 풀은 자기 장면 1트랙만(격리)."""
        g = self._guard()
        a = _box(0.10, 0.10, 0.20, 0.20)   # cam1 장면(좌상단)
        b = _box(0.80, 0.80, 0.90, 0.90)   # cam2 장면(우하단)
        for _ in range(6):
            g._track([a], "hub:cam1")
            g._track([b], "browser")
        pa = g._tracks_by_key["hub:cam1"]
        pb = g._tracks_by_key["browser"]
        self.assertEqual(len(pa), 1, "cam1 풀에 다른 장면 트랙이 섞임(유령)")
        self.assertEqual(len(pb), 1, "browser 풀에 다른 장면 트랙이 섞임(유령)")
        self.assertLess(pa[0]["bbox"][0], 0.5)      # cam1 = 좌상단
        self.assertGreater(pb[0]["bbox"][0], 0.5)   # browser = 우하단

    def test_shared_key_mixes_scenes(self):
        """반례: track_key 를 안 주면(둘 다 browser) 두 장면이 한 풀에 공존 — 3.6 이 고친 유령 증상."""
        g = self._guard()
        a = _box(0.10, 0.10, 0.20, 0.20)
        b = _box(0.80, 0.80, 0.90, 0.90)
        for _ in range(6):
            g._track([a], "browser")
            g._track([b], "browser")
        self.assertGreaterEqual(len(g._tracks_by_key["browser"]), 2,
                                "공유 풀이면 두 장면 트랙이 유령으로 공존해야(격리 필요성 입증)")


if __name__ == "__main__":
    unittest.main()
