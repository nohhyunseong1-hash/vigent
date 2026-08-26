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
        """비식별화가 실패해도 저장 자체를 막으면 안 된다(원본 반환 + 로그).

        ※실패 시 원본이 나가므로 privacy.py 가 반드시 exception 로그를 남긴다."""
        f = _textured_frame()
        with mock.patch.object(privacy, "_mosaic_region", side_effect=RuntimeError("boom")):
            out = privacy.anonymize_faces(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertIsNotNone(out)
        self.assertTrue(np.array_equal(out, f))     # 원본 그대로 반환

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
            # ★[D4-②, 2026-08-24] 반환이 (url, privacy_failed) 튜플로 바뀌었다 —
            #   모자이크 실패 사실을 이벤트 기록에 남겨 **선별 삭제**가 가능하게 하기 위함.
            url, failed = worker._frame_to_dataurl(f, [[0.2, 0.1, 0.6, 0.9]])
        self.assertTrue(called.get("yes"), "증거 저장 경로가 비식별화를 거치지 않는다")
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))
        self.assertFalse(failed, "정상 경로인데 모자이크 실패로 표시됐다")
        base64.b64decode(url.split(",", 1)[1])       # 유효한 JPEG base64


class TestStorageEncryptionCheck(unittest.TestCase):
    """[P1c] 저장 폴더 암호화 검사 — 사실을 사실대로 보고하는가."""

    def setUp(self):
        privacy._storage_cache = {}
        privacy._storage_ts = 0.0

    def test_all_encrypted_reports_true(self):
        with mock.patch.object(privacy, "_efs_encrypted", return_value=True), \
             mock.patch.object(privacy, "_bitlocker_status", return_value="unknown"), \
             mock.patch.object(privacy, "_protected_dirs",
                               return_value=[Path("D:/x/data/evidence")]), \
             mock.patch.object(Path, "exists", return_value=True):
            r = privacy.storage_status(force=True)
        self.assertIs(r["storage_encrypted"], True)

    def test_unencrypted_reports_false_not_unknown(self):
        """★미암호화를 'unknown' 으로 얼버무리지 않는다 — 보호되지 않는 상태는 false 로 드러낸다."""
        with mock.patch.object(privacy, "_efs_encrypted", return_value=False), \
             mock.patch.object(privacy, "_bitlocker_status", return_value="unknown"), \
             mock.patch.object(privacy, "_protected_dirs",
                               return_value=[Path("D:/x/data/evidence")]), \
             mock.patch.object(Path, "exists", return_value=True):
            r = privacy.storage_status(force=True)
        self.assertIs(r["storage_encrypted"], False)

    def test_bitlocker_on_overrides_efs(self):
        """볼륨이 BitLocker 로 보호되면 폴더 EFS 가 없어도 보호된 것으로 본다."""
        with mock.patch.object(privacy, "_efs_encrypted", return_value=False), \
             mock.patch.object(privacy, "_bitlocker_status", return_value="on"), \
             mock.patch.object(privacy, "_protected_dirs",
                               return_value=[Path("D:/x/data/evidence")]), \
             mock.patch.object(Path, "exists", return_value=True):
            r = privacy.storage_status(force=True)
        self.assertIs(r["storage_encrypted"], True)

    def test_no_dirs_is_unknown(self):
        """검사할 폴더가 아직 없으면 판정 불가(false 로 단정하지 않는다)."""
        with mock.patch.object(privacy, "_protected_dirs", return_value=[]), \
             mock.patch.object(privacy, "_bitlocker_status", return_value="unknown"):
            r = privacy.storage_status(force=True)
        self.assertEqual(r["storage_encrypted"], "unknown")

    def test_result_has_no_secrets(self):
        with mock.patch.object(privacy, "_protected_dirs", return_value=[]), \
             mock.patch.object(privacy, "_bitlocker_status", return_value="unknown"):
            r = privacy.storage_status(force=True)
        self.assertEqual(set(r) , {"storage_encrypted", "bitlocker", "efs_by_dir",
                                   "checked_dirs", "note"})


class TestConcurrentAnonymize(unittest.TestCase):
    """[P1a-fix, 2026-08-21] 동시 호출 경합으로 **원본이 저장·전송되던** 결함의 회귀 방지.

    배경: YuNet 은 공유 싱글톤이라 setInputSize→detect 사이에 다른 스레드가 끼어들면
    내부 버퍼 크기가 어긋나 예외가 났다(OpenCV 5 dnn "buf.shape() == m.shape()").
    실서비스에서 워커(1920x1080)와 스냅샷(640x360)이 동시에 불러 **분당 145~160건**
    발생했고(로그 4,054건), 그때마다 except 로 빠져 **비식별화 안 된 원본**이 나갔다.
    """

    def _frame(self, h, w):
        # ★균일한 색으로 만들면 모자이크해도 픽셀이 안 변해 검증이 불가능하다 — 노이즈를 쓴다.
        import numpy as np
        rng = np.random.default_rng(20260821)
        return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)

    def test_concurrent_mixed_sizes_never_returns_original(self):
        """★크기가 다른 프레임을 동시에 넣어도 원본이 그대로 반환되면 안 된다."""
        import threading

        import numpy as np
        boxes = [[0.3, 0.2, 0.5, 0.8]]
        privacy.anonymize_faces(self._frame(1080, 1920), boxes)   # 예열(모델 로드)
        bad = []

        def run(h, w):
            for _ in range(12):
                f = self._frame(h, w)
                out = privacy.anonymize_faces(f, boxes)
                if out is f or np.array_equal(out, f):
                    bad.append((h, w))

        ts = [threading.Thread(target=run, args=(1080, 1920)),
              threading.Thread(target=run, args=(360, 640))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(bad, [], f"원본이 그대로 반환됐다 — 비식별화 실패 {len(bad)}건")

    def test_face_detector_failure_keeps_head_mosaic(self):
        """★얼굴검출기가 실패해도 person 박스 머리 모자이크는 살아남아야 한다.

        이전 동작은 예외 시 out 을 통째로 버리고 원본을 반환해, 이미 적용한 머리
        모자이크까지 사라졌다.
        """
        import numpy as np
        boxes = [[0.3, 0.2, 0.5, 0.8]]
        f = self._frame(720, 1280)
        broken = mock.Mock()
        broken.setInputSize.side_effect = RuntimeError("detector 고장")
        with mock.patch.object(privacy, "_get_cascade", return_value=broken):
            out = privacy.anonymize_faces(f, boxes)
        self.assertFalse(np.array_equal(out, f),
                         "검출기 실패로 머리 모자이크까지 버려졌다(원본 유출)")


if __name__ == "__main__":
    unittest.main()
