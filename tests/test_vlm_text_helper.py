"""P1-6 — rfdetr_service.vlm_text 공통 헬퍼 단위 테스트.

4케이스: ① 성공(raw 추출) ② dict 아님 → None ③ _error → None ④ image None → None.
실제 MLX 모델은 안 띄우고 vlm.summarize_bgr 를 목킹한다(지연 로드라 import 는 가벼움).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import rfdetr_service as R  # noqa: E402


class TestVlmText(unittest.TestCase):
    def setUp(self):
        self._orig = R.vlm.summarize_bgr

    def tearDown(self):
        R.vlm.summarize_bgr = self._orig

    def test_success_raw(self):
        """dict{'raw': 텍스트} → 그 텍스트."""
        R.vlm.summarize_bgr = lambda img, **kw: {"raw": "  위험요인 있음  "}
        self.assertEqual(R.vlm_text(object(), "p"), "위험요인 있음")

    def test_success_joined_fields(self):
        """'raw' 없으면 비-'_' 값들을 join (parsed dict)."""
        R.vlm.summarize_bgr = lambda img, **kw: {"위험요인": "협착", "_meta": "x"}
        out = R.vlm_text(object(), "p")
        self.assertEqual(out, "협착")

    def test_not_dict_returns_none(self):
        R.vlm.summarize_bgr = lambda img, **kw: "그냥 문자열"
        self.assertIsNone(R.vlm_text(object(), "p"))

    def test_error_key_returns_none(self):
        R.vlm.summarize_bgr = lambda img, **kw: {"_error": "load failed", "raw": "x"}
        self.assertIsNone(R.vlm_text(object(), "p"))

    def test_exception_returns_none(self):
        def _boom(img, **kw):
            raise RuntimeError("vlm down")
        R.vlm.summarize_bgr = _boom
        self.assertIsNone(R.vlm_text(object(), "p"))

    def test_none_image_returns_none(self):
        # image None 은 summarize 호출 없이 즉시 None
        R.vlm.summarize_bgr = lambda img, **kw: {"raw": "should not be used"}
        self.assertIsNone(R.vlm_text(None, "p"))

    def test_empty_text_returns_none(self):
        R.vlm.summarize_bgr = lambda img, **kw: {"raw": "   "}
        self.assertIsNone(R.vlm_text(object(), "p"))


if __name__ == "__main__":
    unittest.main()
