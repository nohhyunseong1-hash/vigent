"""track_debug 계측이 **person 을 놓치지 않는지** 지키는 회귀 테스트.

배경(2026-08-26 학원 방문 전 리허설에서 실측): 계측이 `GuardAgent._track_iou` 안에 있었는데,
운영 설정 `track.algo: bytetrack` 에서는 `_track_bytetrack` 이 person 을 먼저 떼어내고
나머지 클래스만 `_track_iou` 로 넘긴다. 그래서 `data/track_debug.jsonl` 에 Hardhat 624건이
쌓이는 동안 person 은 **0건**이었다 — 계측의 주 대상이 통째로 빠진 것이다. 현장에서
20분을 수집해도 판정 재료가 하나도 안 남는 상태였다.

수정: 계측을 디스패처 `_track` 으로 올려 algo 와 무관하게 fresh 원본 전체를 기록한다.
이 테스트는 그 위치가 되돌아가는 것을 막는다.
"""
import unittest

from _source_probe import code_of

GUARD = "vigent-core/agents/guard.py"


class TrackDebugCoversPerson(unittest.TestCase):
    def test_계측은_디스패처에서_호출된다(self):
        """`_track` 이 _dbg_write 를 부른다 — 여기서만 person 포함 fresh 를 볼 수 있다."""
        src = code_of(GUARD, "_track")
        self.assertIn("VIGENT_TRACK_DEBUG", src,
                      "_track 에서 계측 스위치를 읽어야 한다(algo 무관 기록의 전제)")
        self.assertIn("_dbg_write", src, "_track 이 계측 기록을 호출해야 한다")

    def test_iou_트래커_안에는_계측이_없다(self):
        """`_track_iou` 로 되돌리면 bytetrack 의 person 이 다시 빠진다 — 금지."""
        src = code_of(GUARD, "_track_iou")
        self.assertNotIn("VIGENT_TRACK_DEBUG", src,
                         "계측이 _track_iou 로 돌아갔다 — bytetrack 에서 person 이 기록되지 않는다")
        self.assertNotIn("track_debug.jsonl", src,
                         "기록 write 가 _track_iou 로 돌아갔다 — 위와 같은 사고가 재발한다")

    def test_bytetrack_이_person_을_분리한다는_전제_확인(self):
        """이 테스트의 근거 자체를 고정 — 분리가 사라지면 전제가 바뀐 것이니 같이 검토한다."""
        src = code_of(GUARD, "_track_bytetrack")
        self.assertIn("_track_iou(other", src.replace(" ", ""),
                      "_track_bytetrack 이 person 을 뺀 other 만 _track_iou 로 넘긴다는 전제")

    def test_기록_필드가_분석기_계약을_지킨다(self):
        """benchmarks/b_passthru_2fps_check.py 가 읽는 필드(label·conf·bbox)를 계속 남긴다."""
        src = code_of(GUARD, "_dbg_write")
        for key in ('"label"', '"conf"', '"bbox"', '"fresh"', '"tracks"'):
            self.assertIn(key, src, f"분석기가 쓰는 {key} 필드가 기록에서 빠졌다")


if __name__ == "__main__":
    unittest.main()
