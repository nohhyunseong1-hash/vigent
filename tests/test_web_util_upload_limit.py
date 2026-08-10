"""[S2-수정] decode_data_url 업로드 크기 상한 회귀 테스트.

정상 크기(수백KB급) 프레임은 기존과 동일하게 디코딩되고, 설정 상한을 넘는 페이로드는
디코딩 전에 413(HTTPException)으로 거절됨을 확인한다.
"""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import web_util  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _jpeg_data_url(h: int = 480, w: int = 640) -> str:
    import cv2
    img = np.zeros((h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


class TestUploadSizeLimit(unittest.TestCase):
    def test_normal_frame_decodes_unaffected(self):
        url = _jpeg_data_url()
        img = web_util.decode_data_url(url)
        self.assertIsNotNone(img)
        self.assertEqual(img.shape[:2], (480, 640))

    def test_oversized_payload_raises_413(self):
        # 설정 상한을 낮춰 실제로 수백KB 짜리 문자열도 "초과"로 취급되게 만든다(테스트 전용).
        with mock.patch.object(web_util, "_max_image_mb", return_value=0.001):  # ~1KB 상한
            url = _jpeg_data_url()  # 정상 프레임(보통 수십KB 이상) → 이 초저상한은 넘긴다
            with self.assertRaises(HTTPException) as cm:
                web_util.decode_data_url(url)
            self.assertEqual(cm.exception.status_code, 413)

    def test_default_config_allows_up_to_10mb(self):
        # 기본값(tuning.yaml 미설정 시 10)이 실제로 10인지 — 회귀 방지(값이 조용히 바뀌면 여기서 걸림)
        self.assertEqual(web_util._max_image_mb(), 10.0)

    def test_invalid_data_url_still_returns_none(self):
        self.assertIsNone(web_util.decode_data_url("not-a-data-url"))
        self.assertIsNone(web_util.decode_data_url(""))


if __name__ == "__main__":
    unittest.main()
