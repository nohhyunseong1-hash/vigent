"""test_iris.py — 홍채 요소 + vault 정책 검증 (시뮬레이터 사용, NIR 하드웨어 불필요)

실행: cd ~/Desktop/VIGENT && python -m unittest vigentFacialRecognition.tests.test_iris
"""
import os
import pathlib
import tempfile
import unittest

os.environ["VIGENT_IRIS_ENABLED"] = "1"          # 홍채 옵트인(테스트 한정)

from vigentFacialRecognition import config
from vigentFacialRecognition.iris import (IrisRecognizer, IrisStore, NullIrisProvider,
                                          SimIrisProvider)
from vigentFacialRecognition.mfa import DEFAULT_POLICIES, IrisFactor, PolicyEngine


def fresh_store():
    s = IrisStore()
    s.PATH = pathlib.Path(tempfile.mkdtemp()) / "iris.npz"
    s._ids, s._codes, s._masks = [], [], []
    return s


class TestIrisMatching(unittest.TestCase):
    def test_same_eye_matches_different_rejects(self):
        config.IRIS_ENABLED = True
        rec = IrisRecognizer(provider=SimIrisProvider(), store=fresh_store())
        rec.enroll("hong", {"seed": "hong-eye"})
        # 같은 눈(같은 시드, 촬영 변동만) → 일치
        pid, hd, _ = rec.identify({"seed": "hong-eye", "noise": 0.05})
        self.assertEqual(pid, "hong"); self.assertLess(hd, config.IRIS_HAMMING_THRESHOLD)
        # 다른 눈 → 미일치
        pid2, hd2, _ = rec.identify({"seed": "kim-eye"})
        self.assertIsNone(pid2); self.assertGreater(hd2, config.IRIS_HAMMING_THRESHOLD)

    def test_hardware_not_connected_is_undecided(self):
        config.IRIS_ENABLED = True
        rec = IrisRecognizer(provider=NullIrisProvider(), store=fresh_store())
        pid, hd, reason = rec.identify({"seed": "hong-eye"})
        self.assertIsNone(pid); self.assertIn("미연결", reason)


class TestVaultPolicy(unittest.TestCase):
    def setUp(self):
        config.IRIS_ENABLED = True
        self.eng = PolicyEngine()
        self.vault = DEFAULT_POLICIES["vault"]            # [[iris,card],[iris,pin]]
        self.rec = IrisRecognizer(provider=SimIrisProvider(), store=fresh_store())
        self.rec.enroll("hong", {"seed": "hong-eye"})
        self.iris = IrisFactor(recognizer=self.rec)

    def test_iris_plus_card_grants(self):
        from vigentFacialRecognition.mfa import FactorResult
        results = {
            "iris": self.iris.check({"seed": "hong-eye", "noise": 0.04}),
            "card": FactorResult("card", True, subject_id="hong"),
        }
        d = self.eng.decide(self.vault, results)
        self.assertEqual(d.decision, "GRANT"); self.assertEqual(d.subject_id, "hong")

    def test_iris_alone_stepup(self):
        results = {"iris": self.iris.check({"seed": "hong-eye"})}
        d = self.eng.decide(self.vault, results)
        self.assertEqual(d.decision, "STEP_UP")          # 카드 또는 PIN 추가 필요

    def test_iris_card_identity_conflict_denies(self):
        from vigentFacialRecognition.mfa import FactorResult
        results = {
            "iris": self.iris.check({"seed": "hong-eye"}),   # hong
            "card": FactorResult("card", True, subject_id="kim"),
        }
        d = self.eng.decide(self.vault, results)
        self.assertEqual(d.decision, "DENY")


if __name__ == "__main__":
    unittest.main()
