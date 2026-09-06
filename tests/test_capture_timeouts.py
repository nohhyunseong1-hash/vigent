"""[CODE_REVIEW M5-1·M5-2·M5-4·M5-7] 캡처 열기/읽기 타임아웃·FFmpeg 옵션 단일화·열기 실패 로그·포즈 지연 로드 락.

실측(2026-09-06, cv2 5.0/FFmpeg 7.1, 죽은 IP): 기본 VideoCapture() 123.4s 블로킹 · FFmpeg timeout 옵션 98.8s(무효) ·
OpenCV OPEN/READ_TIMEOUT_MSEC 5000 → 5.06s. 계약:
  ① 스트림 소스는 CAP_FFMPEG + OPEN/READ 타임아웃(_RTSP_TIMEOUT_MS)으로 열고, 웹캠(정수)·파일은 기본 백엔드
  ② FFmpeg 옵션은 모듈 상단 한 곳(_FFMPEG_CAPTURE_OPTIONS, 저지연 포함) — _open() 은 env 를 건드리지 않는다
  ③ 열기 실패는 WARNING "열기 실패" 로 구분해 남긴다
  ④ /cameras/{cid}/test 는 타임아웃 안에 응답한다(캡처가 멈춰도)
  ⑤ _PoseModel 지연 로드는 N 스레드가 동시에 불러도 1회
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker as W  # noqa: E402


class _FakeCap:
    def __init__(self, opened=True):
        self._opened = opened

    def isOpened(self):
        return self._opened

    def set(self, *a):
        return True

    def read(self):
        return False, None

    def release(self):
        pass


class OpenCaptureTimeouts(unittest.TestCase):
    def test_stream_uses_ffmpeg_backend_with_timeouts(self):
        calls = []

        def _vc(*a, **k):
            calls.append(a)
            return _FakeCap(True)
        with mock.patch.object(W.cv2, "VideoCapture", side_effect=_vc):
            W._open_capture("rtsp://192.0.2.1:554/s")
        self.assertEqual(len(calls), 1)
        src, backend, props = calls[0]
        self.assertEqual(backend, W.cv2.CAP_FFMPEG)
        self.assertEqual(props, [W.cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, W._RTSP_TIMEOUT_MS,
                                 W.cv2.CAP_PROP_READ_TIMEOUT_MSEC, W._RTSP_TIMEOUT_MS])
        self.assertGreaterEqual(W._RTSP_TIMEOUT_MS, 1000)
        self.assertLessEqual(W._RTSP_TIMEOUT_MS, 15000)

    def test_webcam_index_uses_default_backend(self):
        calls = []
        with mock.patch.object(W.cv2, "VideoCapture", side_effect=lambda *a, **k: (calls.append(a) or _FakeCap())):
            W._open_capture("0")
        self.assertEqual(calls, [(0,)])

    def test_ffmpeg_options_single_source_of_truth(self):
        self.assertIn("nobuffer", W._FFMPEG_CAPTURE_OPTIONS)
        self.assertIn("low_delay", W._FFMPEG_CAPTURE_OPTIONS)
        self.assertIn("rtsp_transport;tcp", W._FFMPEG_CAPTURE_OPTIONS)
        sc = W._StreamCapture("rtsp://192.0.2.1/s", "t")
        with mock.patch.dict(os.environ, {"OPENCV_FFMPEG_CAPTURE_OPTIONS": "SENTINEL"}), \
                mock.patch.object(W, "_open_capture", return_value=_FakeCap()):
            sc._open()
            self.assertEqual(os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"], "SENTINEL", "_open 이 env 를 다시 건드린다")

    def test_open_failure_is_logged_as_open_failure(self):
        with mock.patch.object(W.cv2, "VideoCapture", return_value=_FakeCap(False)), \
                self.assertLogs("vigent.worker", level="WARNING") as cm:
            W._open_capture("rtsp://user:pw@192.0.2.1/s")
        self.assertTrue(any("열기 실패" in line for line in cm.output))
        self.assertFalse(any("user:pw" in line for line in cm.output), "자격증명이 로그에 새면 안 된다")


class CameraTestEndpointTimeout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        from _isolate import isolate_alerts
        from fastapi.testclient import TestClient
        cls.main = main
        cls._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        cls.addClassCleanup(isolate_alerts())
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.main._API_TOKEN = cls._saved_token

    def test_hung_capture_returns_within_timeout(self):
        from routers import cameras as C

        def _hang(src):
            time.sleep(3.0)
            return _FakeCap(False)
        with mock.patch.object(C._reg, "source_of", return_value="rtsp://192.0.2.1:554/s"), \
                mock.patch.object(W, "_open_capture", side_effect=_hang), \
                mock.patch.object(W, "_RTSP_TIMEOUT_MS", 200):
            t0 = time.time()
            r = self.client.post("/cameras/anycam/test").json()
            dt = time.time() - t0
        self.assertFalse(r["ok"])
        self.assertIn("시간 초과", r["error"])
        self.assertLess(dt, 2.5, f"타임아웃 안에 응답해야 한다: {dt:.1f}s")


class PoseModelLoadOnce(unittest.TestCase):
    def test_concurrent_lazy_load_creates_one_detector(self):
        import types
        created = []

        class _Fake:
            def __init__(self):
                created.append(1)
                time.sleep(0.05)

            def persons(self, frame, bboxes=None):
                return []
        fake = types.ModuleType("pose.rtmpose_adapter")
        fake.RtmPoseDetector = _Fake
        saved = sys.modules.get("pose.rtmpose_adapter")
        sys.modules["pose.rtmpose_adapter"] = fake
        try:
            pm = W._PoseModel()
            ths = [threading.Thread(target=lambda: pm.persons(None, [[0, 0, 1, 1]])) for _ in range(5)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
        finally:
            if saved is None:
                sys.modules.pop("pose.rtmpose_adapter", None)
            else:
                sys.modules["pose.rtmpose_adapter"] = saved
        self.assertEqual(len(created), 1, f"포즈 모델이 {len(created)}회 로드됐다(경합)")


if __name__ == "__main__":
    unittest.main()
