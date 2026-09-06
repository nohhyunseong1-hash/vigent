"""[S2-수정] worker.state["error"](→ GET /worker/status·/workers로 그대로 노출)에 RTSP
자격증명이 원문으로 남지 않는지 회귀 확인. camera_registry.scrub_credentials() 단위 테스트도
함께 포함한다.
"""
import sys
import threading
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import camera_registry  # noqa: E402
import worker  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402

_FAKE_CRED_URL = "rtsp://admin:s3cr3tPW@192.168.1.50:554/stream1"


def _ctx_with_source(source: str) -> worker._FrameCtx:
    mtrack = type("M", (), {"update": lambda self, d, t: []})()
    etrack = type("E", (), {"update": lambda self, f, t, b: []})()
    return worker._FrameCtx(["person"], [], mtrack, etrack, False, 30.0,
                            ROOT / "data" / "dataset" / "images", "TESTCAM", source)


class _RaisingGuardWithUrl:
    """실제 cv2/FFmpeg가 연결 실패 메시지에 URL을 그대로 넣는 상황을 재현."""
    def detect(self, frame, detectors=None, track_key="default"):
        raise RuntimeError(f"Can't open stream: {_FAKE_CRED_URL}")


class TestScrubCredentials(unittest.TestCase):
    def test_scrubs_credential_embedded_in_longer_message(self):
        msg = f"OpenCV(4.8.0) error: {_FAKE_CRED_URL} 열기 실패"
        out = camera_registry.scrub_credentials(msg)
        self.assertNotIn("admin", out)
        self.assertNotIn("s3cr3tPW", out)
        self.assertIn("***:***@192.168.1.50:554/stream1", out)

    def test_leaves_plain_text_unchanged(self):
        msg = "프레임 읽기 실패(소스 확인)"
        self.assertEqual(camera_registry.scrub_credentials(msg), msg)

    def test_empty_and_none_safe(self):
        self.assertEqual(camera_registry.scrub_credentials(""), "")
        self.assertEqual(camera_registry.scrub_credentials(None), "")


class TestWorkerStateErrorMasking(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())     # [4단계 ④] TESTCAM 행이 운영 큐에 남지 않게(#82)
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.lock = threading.Lock()
        self.worker = worker.Worker()

    def test_process_frame_exception_masks_credentials_in_state_error(self):
        ctx = _ctx_with_source(_FAKE_CRED_URL)
        self.worker._process_frame(self.frame, 100.0, _RaisingGuardWithUrl(), self.lock, ctx)
        err = self.worker.state.get("error", "")
        self.assertIn("error", self.worker.state)
        self.assertNotIn("admin", err)
        self.assertNotIn("s3cr3tPW", err)
        # status()가 그대로 반환하는 필드이므로(worker.py:501 dict(self.state)) 동일하게 확인
        self.assertNotIn("s3cr3tPW", self.worker.status().get("error", ""))


class TestWorkerStartMasksSource(unittest.TestCase):
    """[S2-수정] 스모크 테스트로 발견된 추가 유출 경로 — Worker.start()가 state["source"]에
    원본 URL을 그대로 저장해 /worker/status·/workers 응답에 자격증명이 평문으로 찍혔다
    (worker.py:473, 승인 범위(state["error"])를 벗어나지만 동일 API·동일 근본원인이라 함께 수정)."""

    def test_start_stores_masked_source_in_state(self):
        w = worker.Worker()
        try:
            result = w.start(guard=None, lock=threading.Lock(),
                             source=_FAKE_CRED_URL, name="t", fps=1.0)
            self.assertIn("***:***@", result["status"]["source"])
            self.assertNotIn("admin", result["status"]["source"])
            self.assertNotIn("s3cr3tPW", result["status"]["source"])
            self.assertNotIn("s3cr3tPW", w.status()["source"])
        finally:
            w.stop()


if __name__ == "__main__":
    unittest.main()
