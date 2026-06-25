"""test_mfa.py — 다중 인증 정책 엔진 검증 (실제 카메라/생체 불필요)

실행: cd ~/Desktop/VIGENT && python -m unittest vigentFacialRecognition.tests.test_mfa
"""
import unittest

from vigentFacialRecognition.mfa import (DEFAULT_POLICIES, AuthDecision, FactorResult,
                                         PolicyEngine, Policy)


def F(name, ok, subject=None):
    return FactorResult(name, ok, subject_id=subject, confidence=1.0 if ok else 0.0)


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.eng = PolicyEngine()
        self.basic = DEFAULT_POLICIES["basic"]   # [[face],[card,pin]]
        self.dusty = DEFAULT_POLICIES["dusty"]   # [[card,face],[card,pin]]
        self.high = DEFAULT_POLICIES["high"]     # [[card,face,pin]]

    def test_face_only_grants_in_basic(self):
        d = self.eng.decide(self.basic, {"face": F("face", True, "hong")})
        self.assertEqual(d.decision, "GRANT"); self.assertEqual(d.subject_id, "hong")

    def test_face_alone_not_enough_in_dusty(self):
        # 고분진: 얼굴만으론 부족 → 카드 추가 요구(step-up)
        d = self.eng.decide(self.dusty, {"face": F("face", True, "hong")})
        self.assertEqual(d.decision, "STEP_UP")
        self.assertIn("card", d.needed)

    def test_masked_face_falls_back_to_card_pin(self):
        # 핵심 산업 시나리오: 마스크로 얼굴 판정불가 → 카드+PIN으로 통과
        results = {
            "face": F("face", False),                 # 판정불가
            "card": F("card", True, "hong"),
            "pin": F("pin", True, "hong"),
        }
        d = self.eng.decide(self.dusty, results)
        self.assertEqual(d.decision, "GRANT"); self.assertEqual(d.subject_id, "hong")
        self.assertEqual(sorted(d.satisfied), ["card", "pin"])

    def test_identity_conflict_denies(self):
        # 얼굴은 hong, 카드는 kim → 충돌 거부
        results = {"face": F("face", True, "hong"), "card": F("card", True, "kim")}
        d = self.eng.decide(self.dusty, results)
        self.assertEqual(d.decision, "DENY")
        self.assertTrue(any("충돌" in r for r in d.reasons))

    def test_wrong_pin_denies_or_stepup(self):
        results = {"card": F("card", True, "hong"), "pin": F("pin", False, "hong")}
        d = self.eng.decide(self.high, results)   # 고보안: 카드+얼굴+PIN 필요
        self.assertIn(d.decision, ("STEP_UP", "DENY"))
        self.assertNotEqual(d.decision, "GRANT")

    def test_fail_safe_default_deny(self):
        d = self.eng.decide(self.dusty, {})        # 아무 요소 없음
        self.assertEqual(d.decision, "DENY")

    def test_high_needs_all_three(self):
        results = {"card": F("card", True, "hong"), "face": F("face", True, "hong"),
                   "pin": F("pin", True, "hong")}
        d = self.eng.decide(self.high, results)
        self.assertEqual(d.decision, "GRANT")
        self.assertEqual(sorted(d.satisfied), ["card", "face", "pin"])


class TestPinHash(unittest.TestCase):
    def test_pin_roundtrip(self):
        from vigentFacialRecognition.mfa import PinStore
        import tempfile, pathlib
        s = PinStore()
        s.PATH = pathlib.Path(tempfile.mkdtemp()) / "pins.json"
        s._m = {}
        s.set_pin("hong", "8273")
        self.assertTrue(s.verify("hong", "8273"))
        self.assertFalse(s.verify("hong", "0000"))
        # 평문이 저장되지 않았는지
        self.assertNotIn("8273", s.PATH.read_text())


if __name__ == "__main__":
    unittest.main()
