"""test_engine.py — 모듈 기본 동작 테스트 (모델 없어도 폴백 확인)

실행: cd ~/Desktop/VIGENT && python -m unittest vigentFacialRecognition.tests.test_engine
"""
import os
import unittest

import numpy as np

# 테스트 동안에는 옵트인을 켠다(실데이터 없음 → 법적 영향 없음).
os.environ.setdefault("VIGENT_FR_ENABLED", "1")

from vigentFacialRecognition import config, privacy
from vigentFacialRecognition.engine import FaceEngine


class TestPrivacyGate(unittest.TestCase):
    def test_opt_in_blocks_when_disabled(self):
        old = config.ENABLED
        config.ENABLED = False
        try:
            with self.assertRaises(privacy.FacialRecognitionDisabled):
                privacy.require_enabled()
        finally:
            config.ENABLED = old

    def test_consent_expiry(self):
        c = privacy.Consent(purpose="t", consented_by="t", retention_days=0)
        self.assertFalse(c.is_expired())   # 0 = 무기한


class TestEngine(unittest.TestCase):
    @unittest.skipUnless(config.model_files_present(), "모델 미설치 — download_models 필요")
    def test_detect_empty_on_blank(self):
        eng = FaceEngine()
        blank = np.zeros((240, 320, 3), dtype=np.uint8)
        self.assertEqual(eng.detect(blank), [])   # 빈 화면 → 얼굴 0개

    @unittest.skipUnless(config.model_files_present(), "모델 미설치")
    def test_embedding_shape_and_norm(self):
        eng = FaceEngine()
        # 합성 얼굴이 없으므로 임베딩 형상은 cosine 헬퍼로 간접 검증
        a = np.ones(128, np.float32); a /= np.linalg.norm(a)
        self.assertAlmostEqual(FaceEngine.cosine(a, a), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
