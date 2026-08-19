"""[Q9] ort_tune 테스트 — ★기본 off 보장이 핵심이다(규칙6: 켜야만 동작이 바뀐다)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import ort_tune  # noqa: E402


class _Fake:
    """rtmlib BaseTool 흉내 — .session + .onnx_model 을 가진 객체."""

    def __init__(self, path: str):
        self.onnx_model = path
        self.session = object()

    def __call__(self, *a, **k):        # ★rtmlib 처럼 callable 이다(탐색이 걸러내면 안 됨)
        return None


class _FakeBody:
    def __init__(self):
        self.det_model = _Fake("det.onnx")
        self.pose_model = _Fake("pose.onnx")
        self.one_stage = False


class TestDefaultOff(unittest.TestCase):
    """★가장 중요한 계약: 설정을 안 켜면 아무것도 바뀌지 않는다."""

    def test_disabled_by_default(self):
        with mock.patch.object(ort_tune.tuning, "val", side_effect=lambda s, k, d, env=None: d):
            self.assertFalse(ort_tune.enabled())
            self.assertIsNone(ort_tune.session_options())

    def test_retune_is_noop_when_disabled(self):
        body = _FakeBody()
        before = (body.det_model.session, body.pose_model.session)
        with mock.patch.object(ort_tune.tuning, "val", side_effect=lambda s, k, d, env=None: d):
            n = ort_tune.retune(body)
        self.assertEqual(n, 0, "비활성인데 세션을 건드렸다")
        self.assertIs(body.det_model.session, before[0])
        self.assertIs(body.pose_model.session, before[1])


class TestSessionDiscovery(unittest.TestCase):
    def test_finds_callable_tools(self):
        """rtmlib 의 YOLOX·RTMPose 는 __call__ 이 있다 — callable 을 걸러내면 못 찾는다."""
        found = ort_tune._find_tools(_FakeBody())
        names = sorted(t.onnx_model for t in found)
        self.assertEqual(names, ["det.onnx", "pose.onnx"])

    def test_no_sessions_on_plain_object(self):
        self.assertEqual(ort_tune._find_tools(object()), [])


class TestEnabledPath(unittest.TestCase):
    def _cfg(self, **kw):
        base = {"tune_sessions": True, "intra_op_threads": 4, "allow_spinning": False}
        base.update(kw)
        return mock.patch.object(ort_tune.tuning, "val",
                                 side_effect=lambda s, k, d, env=None: base.get(k, d))

    def test_options_built_when_enabled(self):
        with self._cfg():
            so = ort_tune.session_options()
        if so is None:
            self.skipTest("onnxruntime 미설치")
        self.assertEqual(so.intra_op_num_threads, 4)
        self.assertEqual(so.inter_op_num_threads, 1)

    def test_intra_threads_floor(self):
        with self._cfg(intra_op_threads=0):
            self.assertGreaterEqual(ort_tune.intra_threads(), 1)

    def test_bad_value_falls_back(self):
        with self._cfg(intra_op_threads="이상한값"):
            self.assertEqual(ort_tune.intra_threads(), 4)

    def test_retune_survives_session_failure(self):
        """세션 재구성이 실패해도 예외를 올리지 않고 기존 세션을 남긴다(무중단)."""
        body = _FakeBody()
        orig = body.pose_model.session
        with self._cfg(), mock.patch.object(ort_tune, "session_options", return_value=object()), \
             mock.patch("onnxruntime.InferenceSession", side_effect=RuntimeError("주입 실패")):
            n = ort_tune.retune(body)
        self.assertEqual(n, 0)
        self.assertIs(body.pose_model.session, orig, "실패했는데 세션이 사라졌다")


if __name__ == "__main__":
    unittest.main()
