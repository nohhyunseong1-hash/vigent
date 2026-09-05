"""[B4] 콜드 스타트 예열 ↔ 워치독 분리 테스트.

검증 대상:
  1. 예열 전 phase=starting, 완료 후 ready, 실패 시 failed
  2. 예열이 더미 추론까지 실제로 호출하는가(로드만으로는 첫 프레임 지연이 안 사라짐)
  3. 예열 성공 시에만 on_ready 콜백(=워커 기동)이 불린다 — 차가운 모델에 워커를 붙이지 않는다
  4. 워커 hang 워치독의 startup grace 가 config 에서 오고 기본 15초 임계는 유지된다
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import readiness  # noqa: E402


def _drain_stray_warmups(timeout: float = 90.0) -> None:
    """[R12 flaky, 2026-09-06 실측] 다른 테스트 모듈이 FastAPI 앱 startup 으로 띄운 **실모델 예열
    스레드**("vigent-warmup", 20초+)가 그 테스트가 끝난 뒤에도 살아서 전역 readiness 상태에
    _mark(READY) 를 쓴다. 이 모듈이 FAILED 를 기대하는 순간 그 스레드가 READY 로 덮으면
    실패한다(전체 스위트 -v 로그: audit/unittest_flaky_2026-09-06_run3.log —
    test_on_ready_not_called_when_warmup_fails, 'ready' != 'failed'). 단독 실행은 항상 통과.
    → 검증 전에 남아 있는 예열 스레드를 기다려 상태 경합을 없앤다(테스트 격리 결함이지 제품 결함 아님)."""
    for t in threading.enumerate():
        if t.name == "vigent-warmup" and t is not threading.current_thread():
            t.join(timeout)


class _FakeGuard:
    """detect 호출을 기록하는 최소 가드."""

    def __init__(self, fail=False, delay=0.0):
        self.calls = []
        self.fail = fail
        self.delay = delay

    def detect(self, img, detectors=None, track_key=None):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("warmup boom")
        self.calls.append(tuple(detectors or []))
        return {"detections": []}


class TestWarmup(unittest.TestCase):
    def setUp(self):
        _drain_stray_warmups()
        readiness._mark(readiness.STARTING)
        with readiness._lock:
            readiness._state["started_at"] = time.time()
            readiness._state["warmup_s"] = None

    def test_starts_in_starting_phase(self):
        self.assertEqual(readiness.phase(), readiness.STARTING)
        self.assertFalse(readiness.is_ready())

    def test_warmup_marks_ready_and_records_time(self):
        g = _FakeGuard()
        r = readiness.warmup(g, ["person"])
        self.assertTrue(r["ok"])
        self.assertEqual(readiness.phase(), readiness.READY)
        self.assertTrue(readiness.is_ready())
        self.assertIsNotNone(readiness.snapshot()["warmup_s"])

    def test_warmup_runs_dummy_inference_per_slot(self):
        """로드만이 아니라 슬롯마다 **실제 추론 1회**를 돌려야 커널이 예열된다."""
        g = _FakeGuard()
        readiness.warmup(g, ["person", "ppe", "fire_smoke"])
        self.assertEqual(g.calls, [("person",), ("ppe",), ("fire_smoke",)])

    def test_warmup_failure_marks_failed_not_ready(self):
        g = _FakeGuard(fail=True)
        r = readiness.warmup(g, ["person"])
        self.assertFalse(r["ok"])
        self.assertEqual(readiness.phase(), readiness.FAILED)
        self.assertFalse(readiness.is_ready())
        self.assertIn("boom", readiness.snapshot()["error"])

    def test_on_ready_called_only_after_success(self):
        """★워커는 예열이 끝난 뒤에만 붙어야 한다 — 차가운 모델에 붙으면 첫 검출이
        콜드 로드를 떠안아 워치독을 넘긴다(B4 의 근본 원인)."""
        done = threading.Event()
        g = _FakeGuard()
        readiness.start_background(g, on_ready=done.set, detectors=["person"]).join(timeout=5)
        self.assertTrue(done.wait(timeout=5))
        self.assertEqual(readiness.phase(), readiness.READY)

    def test_on_ready_not_called_when_warmup_fails(self):
        called = threading.Event()
        g = _FakeGuard(fail=True)
        readiness.start_background(g, on_ready=called.set, detectors=["person"]).join(timeout=5)
        time.sleep(0.2)
        self.assertFalse(called.is_set())
        self.assertEqual(readiness.phase(), readiness.FAILED)

    def test_snapshot_has_no_secrets(self):
        keys = set(readiness.snapshot().keys())
        self.assertEqual(keys, {"phase", "warmup_s", "elapsed_s", "error"})


class TestWatchdogGrace(unittest.TestCase):
    def test_grace_and_timeout_are_config_driven(self):
        """회피용 환경변수(VIGENT_HANG_TIMEOUT=60)에 의존하지 않고 config 기본값으로 동작해야 한다.

        재부팅하면 사라지는 환경변수는 '존재하지 않는 설정'이다(B4 배경)."""
        import worker
        # 기본 워치독 임계는 느슨해지지 않았다 — 15초 유지
        self.assertEqual(worker._HANG_TIMEOUT, 15.0)
        # 유예는 콜드 로드(실측 12.5초)보다 넉넉해야 의미가 있다
        self.assertGreaterEqual(worker._STARTUP_GRACE, 30.0)


class TestRequiredWeightsGuard(unittest.TestCase):
    """[B8] 필수 가중치가 없으면 조용히 폴백하지 않고 명시적으로 실패해야 한다."""

    def setUp(self):
        _drain_stray_warmups()
        readiness._mark(readiness.STARTING)

    def test_missing_required_weight_fails_warmup(self):
        with mock.patch.object(readiness, "required_weights_missing",
                               return_value=["ppe_rfdetr_v1.pth"]):
            g = _FakeGuard()
            r = readiness.warmup(g, ["person"])
        self.assertFalse(r["ok"])
        self.assertEqual(readiness.phase(), readiness.FAILED)
        self.assertIn("fetch_weights.py", r["error"])      # 조치 방법이 메시지에 있어야 한다
        self.assertEqual(g.calls, [])                      # 추론 시도조차 하지 않는다

    def test_present_weights_allow_warmup(self):
        with mock.patch.object(readiness, "required_weights_missing", return_value=[]):
            r = readiness.warmup(_FakeGuard(), ["person"])
        self.assertTrue(r["ok"])

    def test_missing_list_reads_manifest_required_only(self):
        """선택(required=false) 파일이 없다고 기동을 막으면 안 된다."""
        missing = readiness.required_weights_missing()
        self.assertNotIn("yolo11m.pt", missing)            # 폴백용 — 없어도 정상
        self.assertNotIn("yolov8n-pose.pt", missing)       # RTMPose 가 주력


if __name__ == "__main__":
    unittest.main()
