"""[P1a] 얼굴 비식별화 테스트.

배경(감사 🟠C1): data_engine.py:12 에 "얼굴 비식별화는 상용 단계 과제" 주석만 있고 구현이
없어, 근로자 얼굴이 담긴 증거 프레임이 그대로 디스크·알림·클라우드로 나갔다.

핵심 검증:
  1. person 박스 머리 영역이 실제로 뭉개졌는가(픽셀 분산 감소로 판정)
  2. ★**원본 프레임은 변하지 않는가** — 검출 정확도 회귀 방지의 핵심
  3. 얼굴/사람이 없으면 원본과 동일
  4. 저장 경로(_frame_to_dataurl)가 비식별화를 실제로 거치는가
"""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import privacy  # noqa: E402


def _textured_frame(h=480, w=640):
    """고주파 무늬 프레임 — 모자이크가 걸리면 분산이 뚜렷이 준다."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)


def _var(img, x1, y1, x2, y2):
    return float(np.var(img[y1:y2, x1:x2].astype(np.float32)))


class TestAnonymize(unittest.TestCase):
    def test_head_region_is_mosaicked(self):
        """★person 박스 머리 영역의 픽셀 분산이 크게 감소해야 한다(= 뭉개졌다)."""
        f = _textured_frame()
        box = [0.25, 0.20, 0.55, 0.90]           # 정규화 person 박스
        out = privacy.anonymize_faces(f, [box])
        h, w = f.shape[:2]
        x1, y1 = int(0.25 * w), int(0.20 * h)
        x2 = int(0.55 * w)
        y2 = int(y1 + (0.90 - 0.20) * h * privacy._head_ratio())
        # 머리 영역 안쪽(여백 제외)에서 비교
        before = _var(f, x1 + 30, y1 + 5, x2 - 30, y2 - 5)
        after = _var(out, x1 + 30, y1 + 5, x2 - 30, y2 - 5)
        self.assertLess(after, before * 0.6,
                        f"머리 영역이 충분히 뭉개지지 않았다(before {before:.0f} → after {after:.0f})")

    def test_original_frame_is_not_modified(self):
        """★★원본 불변 — 실시간 검출 파이프라인이 보는 프레임은 절대 건드리지 않는다.

        이게 깨지면 비식별화가 검출 정확도를 떨어뜨린다(규칙6 위반)."""
        f = _textured_frame()
        snapshot = f.copy()
        privacy.anonymize_faces(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertTrue(np.array_equal(f, snapshot), "원본 프레임이 수정됐다")

    def test_returns_new_array(self):
        f = _textured_frame()
        out = privacy.anonymize_faces(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertIsNot(out, f)

    def test_no_person_no_change_outside_faces(self):
        """사람이 없으면(그리고 haar 도 못 찾으면) 원본과 동일해야 한다."""
        f = _textured_frame()
        with mock.patch.object(privacy, "_get_cascade", return_value=None):
            out = privacy.anonymize_faces(f, [])
        self.assertTrue(np.array_equal(out, f))

    def test_pixel_boxes_also_supported(self):
        """정규화(0~1)뿐 아니라 픽셀 좌표 박스도 처리한다."""
        f = _textured_frame()
        out = privacy.anonymize_faces(f, [[100.0, 50.0, 300.0, 400.0]])
        before = _var(f, 130, 55, 270, 130)
        after = _var(out, 130, 55, 270, 130)
        self.assertLess(after, before * 0.6)

    def test_disabled_by_config_returns_original(self):
        f = _textured_frame()
        with mock.patch.object(privacy, "enabled", return_value=False):
            out = privacy.anonymize_faces(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertIs(out, f)

    def test_failure_returns_original_not_crash(self):
        """비식별화가 실패해도 저장 자체를 막으면 안 된다(원본 반환 + 로그)."""
        f = _textured_frame()
        with mock.patch.object(privacy, "_mosaic_region", side_effect=RuntimeError("boom")):
            out = privacy.anonymize_faces(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertIsNotNone(out)

    def test_status_shape(self):
        s = privacy.status()
        self.assertIn("face_anonymize", s)
        self.assertEqual(s["method"], "mosaic")      # 블러 아님(복원 공격 대비)


class TestEvidencePathWired(unittest.TestCase):
    """저장 경로가 실제로 비식별화를 거치는지 — 배선 회귀 방지."""

    def test_frame_to_dataurl_anonymizes(self):
        import worker
        f = _textured_frame()
        called = {}

        def _spy(frame, boxes=None):
            called["yes"] = True
            return frame

        with mock.patch.object(worker.privacy, "anonymize_faces", side_effect=_spy):
            url = worker._frame_to_dataurl(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertTrue(called.get("yes"), "증거 저장 경로가 비식별화를 거치지 않는다")
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        base64.b64decode(url.split(",", 1)[1])       # 유효한 JPEG base64


if __name__ == "__main__":
    unittest.main()
