"""test_smartloto.py — 그룹 LOTO 상태머신 검증 (가짜 컨트롤러)

실행: cd ~/Desktop/VIGENT && python -m unittest vigentFacialRecognition.tests.test_smartloto
"""
import unittest

from vigentFacialRecognition.smartloto import LotoError, LotoStation


class FakeController:
    """하드웨어 대역 — set_locked 호출을 기록."""
    def __init__(self):
        self.locked = True
        self.calls = []

    def set_locked(self, locked):
        self.locked = locked
        self.calls.append(locked)

    def status(self):
        return {"locked": self.locked, "simulated": True, "port": "(fake)"}


class TestSmartLoto(unittest.TestCase):
    def setUp(self):
        self.hw = FakeController()
        self.st = LotoStation("PRESS-01", self.hw)

    def test_starts_safe_locked(self):
        self.assertEqual(self.st.state, "SAFE_IDLE")
        self.assertTrue(self.hw.locked)            # 시작은 잠금(안전)

    def test_apply_lock_disables_machine(self):
        self.st.apply_lock("hong", "홍길동")
        self.assertEqual(self.st.state, "LOCKED_OUT")
        self.assertFalse(self.st.can_energize())
        self.assertTrue(self.hw.locked)

    def test_group_lock_all_must_clear(self):
        self.st.apply_lock("hong"); self.st.apply_lock("kim")
        self.assertEqual(self.st.snapshot()["lock_count"], 2)
        self.st.remove_lock("hong", by="hong")
        self.assertEqual(self.st.state, "LOCKED_OUT")   # kim 잠금 남음
        self.st.remove_lock("kim", by="kim")
        self.assertEqual(self.st.state, "SAFE_IDLE")    # 전부 해제

    def test_cannot_remove_others_lock(self):
        self.st.apply_lock("hong")
        with self.assertRaises(LotoError):
            self.st.remove_lock("hong", by="kim")       # 타인 해제 금지
        # 관리자 강제해제는 허용
        self.st.remove_lock("hong", by="boss", supervisor=True)
        self.assertEqual(self.st.state, "SAFE_IDLE")

    def test_energize_blocked_while_locked(self):
        self.st.apply_lock("hong")
        with self.assertRaises(LotoError):
            self.st.energize(by="hong")

    def test_energize_when_clear(self):
        self.st.apply_lock("hong"); self.st.remove_lock("hong", by="hong")
        self.st.energize(by="boss")
        self.assertEqual(self.st.state, "ENERGIZED")
        self.assertFalse(self.hw.locked)               # 기동 → 하드웨어 해제

    def test_apply_lock_kills_energized(self):
        self.st.apply_lock("hong"); self.st.remove_lock("hong", by="hong")
        self.st.energize(by="boss")
        self.st.apply_lock("lee")                       # 가동 중 정비 잠금
        self.assertEqual(self.st.state, "LOCKED_OUT")
        self.assertTrue(self.hw.locked)                 # 즉시 비활성


if __name__ == "__main__":
    unittest.main()
